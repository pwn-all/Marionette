'''
    CDP - Chrome Debugger Protocol Python Module
'''


from asyncio import (
    AbstractEventLoop,
    Lock,
    create_subprocess_exec,
    get_event_loop,
    new_event_loop,
    get_running_loop,
    run_coroutine_threadsafe,
    sleep,
    start_server
)
from json import loads
from datetime import datetime
from platform import system as os_platform
from random import randint
from threading import Thread
from typing import List, Tuple

from local_socks.proxy_server import LocalSocks

from aiofiles import open as aio_open
from aiohttp import ClientSession
from aiohttp.client_exceptions import (
    ClientOSError,
    ServerDisconnectedError,
    WSServerHandshakeError,
)


class ChromeDebugg:
    '''
        Chrome Debugger Protocol (CDP) Python Module
    '''

    def __init__(self, profile: dict, masking) -> None:
        self._profile: dict = profile
        self._emulations: List[dict] = masking.get_emulations(
            profile['spoofing']
        )

        self._cmd_id: int = 0
        self._port: int = None

        self._already_tid: List[str] = []
        self._proxy_loop: AbstractEventLoop = []

        self._tid_manager: Lock = Lock()
        self._cmd_id_manager: Lock = Lock()

        self._err: Tuple[Exception] = (
            WSServerHandshakeError, ConnectionResetError, ClientOSError,
            ConnectionAbortedError, ConnectionError, ServerDisconnectedError,
            TimeoutError
        )

    def _background_loop(self, tid: str) -> AbstractEventLoop:
        '''
            Create new asyncio event loop for background task.
            Run this loop "forever" in Thread.

            :param tid: str - thread ID

            Return `AbstractEventLoop`
        '''

        loop = new_event_loop()
        Thread(target=loop.run_forever, name=tid).start()

        return loop

    async def _write_error_log(self, fuction: str, error: Exception) -> None:
        '''Write error to log file
        
        :param function: str - function name
        :param error: Exception - any catched exception
        
        Return `None`'''

        async with aio_open('errors.log', 'a', encoding='utf-8') as err_file:
            await err_file.write(
                f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] ' +
                f'At `{fuction}` error: {error}\n'
            )

    async def read_chrome_config(self) -> dict:
        async with aio_open('chrome_settings.json', 'r', encoding='utf-8') as cconfig:
            return loads(await cconfig.read())

    async def _shutdown(self) -> None:
        '''
            Gracefully shutdown all oppened processes

            Return `None`
        '''

        current_loop = get_running_loop()

        await current_loop.shutdown_default_executor()
        await self._proxy_loop.shutdown_default_executor()

        current_loop.call_soon_threadsafe(current_loop.stop)
        self._proxy_loop.call_soon_threadsafe(self._proxy_loop.stop)

        current_loop.close()

    async def _assing_id(self, body: dict) -> dict:
        '''
            Assign `id` param for CDP request.
            It will increment the value by 1 with each query

            :param body: dict - body of request, like: {'method': ...}

            Return `dict`, like:
            {
                'method': ... (body),
                + 'id': %ID%
            }
        '''

        async with self._cmd_id_manager:
            self._cmd_id += 1

        body.update({'id': self._cmd_id})

        return body

    async def websocket(self, tid: str) -> None:
        '''
            Working with `TabID` and executing emulations

            :param tid: str - TabID like: "28910AAK39K"

            Return `None`
        '''

        async def stop(tid: str) -> None:
            '''
                Gracefully shutdown thread and remove TID

                :param tid: str - thread ID, like: "28910AAK39K"

                Return `None`
            '''

            async with self._tid_manager:
                self._already_tid.remove(tid)

            cur_loop = get_event_loop()
            cur_loop.stop()

        url = f'ws://127.0.0.1:{self._port}/devtools/page/'

        async with ClientSession() as session:
            try:
                async with session.ws_connect(url+tid) as ws:
                    for feature in ('Runtime.enable', 'Page.enable'):
                        await ws.send_json(
                            await self._assing_id({
                                'method': feature,
                                'params': {}
                            })
                        )

                    for emulation in self._emulations:
                        await ws.send_json(await self._assing_id(emulation))

                    for feature in ('Runtime.runIfWaitingForDebugger', 'Network.enable'):
                        await ws.send_json(
                            await self._assing_id({
                                'method': feature,
                                'params': {}
                            })
                        )

                    async for msg in ws:
                        match msg.json().get('method', None):
                            case 'Inspector.detached' |'Inspector.targetCrashed':
                                break
                            case _:
                                print(f'Attached [{tid}] normal: {msg}')
            except self._err:
                pass
            except Exception as e:
                await self._write_error_log('websocket', e)
            finally:
                await session.close()
                run_coroutine_threadsafe(stop(tid), get_event_loop())

    async def _port_used(self, port: int) -> bool:
        '''
            Check if selected ports in use

            :param port: int - port, like: 20808

            Return `bool` as logical result
        '''

        try:
            server = await start_server(
                lambda x, b: x, '127.0.0.1', port,
                family=0
            )
            server.close()
            await server.wait_closed()
        except (PermissionError, OSError):
            return True

        return False

    async def _run_local_proxy(self) -> str:
        '''
            Run local proxy with `gost` because Chrome not support socks auth.

            :param remote_proxy: str - proxy url, like: socks5://user:pass@127.0.0.1:9050

            Return `str`, like: "socks5://127.0.0.1:23230"
        '''

        assert not all(map(
            lambda scheme: not self._profile['proxy'].startswith(scheme),
            ('socks://', 'socks4://', 'socks5://', 'direct://')
        )), "Invalid Proxy Scheme. Only: SOCKS5 is supported"

        if '@' not in self._profile['proxy']:
            return self._profile['proxy']

        while await self._port_used(port := randint(2000, 65530)):
            port = randint(2000, 65530)

        loop = self._background_loop(f'ProxyPort_{port}')
        self._proxy_loop = loop

        run_coroutine_threadsafe(
            LocalSocks(loop, port, self._profile["proxy"]).start_server(),
            loop
        )

        retries = 0

        while not await self._port_used(port):
            assert retries < 20, "Proxy is not started in 20 attempts"
            retries += 1
            await sleep(0.5)

        return f'socks5://127.0.0.1:{port}'

    async def _open_chrome(self) -> str:
        '''
            Open Chrome with Remote Debugging arg. Will set CDP port to `self._port`
        '''

        chrome_config = await self.read_chrome_config()
        exec_path = chrome_config['location'].get(os_platform(), '')

        while await self._port_used(port := randint(2000, 65530)):
            port = randint(2000, 65530)

        try:
            await create_subprocess_exec(
                exec_path, f"--proxy-server={await self._run_local_proxy()}",
                f"--user-data-dir={self._profile['path']}",
                f"--remote-debugging-port={port}", *chrome_config['default_args'],
                close_fds=True
            )
        except Exception as e:
            await self._write_error_log('_open_chrome', e)
            raise OSError

        self._port = port

    async def _await_online(self) -> str:
        '''
            Loop till `self._port` will be not set.
            After successfully obtaining a working port, the script will
            attempt to obtain the `webSocketDebuggerUrl` and return it.

            Return `str`, like: `ws://...`
        '''

        await self._open_chrome()

        url = f'http://127.0.0.1:{self._port}/json/version'
        debugger_url = None

        while not debugger_url:
            async with ClientSession() as session:
                try:
                    async with session.get(url) as resp:
                        debugger_url = (await resp.json())['webSocketDebuggerUrl']
                except self._err:
                    await sleep(0.5)
                finally:
                    await session.close()

        return debugger_url

    async def main(self) -> None:
        '''
            Main worker thread
        '''

        async with ClientSession() as session:
            try:
                async with session.ws_connect(await self._await_online()) as ws:
                    await ws.send_json(
                        await self._assing_id({
                            'method': 'Target.setAutoAttach',
                            'params': {
                                'autoAttach': True,
                                'waitForDebuggerOnStart': True,
                                'flatten': True
                            }
                        })
                    )
                    await ws.send_json(
                        await self._assing_id({
                            'method': 'Target.setDiscoverTargets',
                            'params': {
                                'discover': True
                            }
                        })
                    )

                    async for msg in ws:
                        msg = msg.json()

                        match msg.get('method', None):
                            case 'Target.attachedToTarget' | 'Target.targetCreated':
                                tid = msg['params']['targetInfo']['targetId']

                                if tid in self._already_tid:
                                    continue

                                await ws.send_json(
                                    await self._assing_id({
                                        'method': 'Target.autoAttachRelated',
                                        'params': {
                                            'targetId': tid,
                                            'waitForDebuggerOnStart': True
                                        }
                                    })
                                )

                                async with self._tid_manager:
                                    self._already_tid.append(tid)

                                run_coroutine_threadsafe(
                                    self.websocket(tid),
                                    self._background_loop(tid)
                                )
                            case _:
                                print('Main Loop Message:', msg)
            except self._err:
                pass
            except Exception as e:
                await self._write_error_log('debugger_main', e)
            finally:
                await session.close()
                await self._shutdown()
