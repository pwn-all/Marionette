from asyncio import all_tasks, current_task, gather

from .protocols import LocalTCP


class LocalSocks:
    def __init__(self, loop, port: int, proxy: str):
        assert proxy.startswith('socks5://'), 'Proxy must start from: socks5://'
        self.config = {
            "LISTEN_HOST": "127.0.0.1",
            "LISTEN_PORT": port,
            "PROXY": proxy
        }
        self.loop = loop
        self.server = None

    async def start_server(self) -> None:
        self.server = await self.loop.create_server(
            lambda: LocalTCP(self.config),
            self.config['LISTEN_HOST'],
            self.config['LISTEN_PORT'],
        )

    async def close_server(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def shut_down(self) -> None:
        await self.close_server()

        tasks = [t for t in all_tasks() if t is not current_task()]
        [task.cancel() for task in tasks]

        await gather(*tasks, return_exceptions=True)

        self.loop.stop()
