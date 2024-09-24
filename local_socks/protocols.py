from asyncio import Protocol, get_event_loop, wait_for
from asyncio.selector_events import _SelectorSocketTransport as AIOSST
from asyncio.streams import StreamReader
from socket import AF_INET, AF_INET6, gaierror, inet_ntop, inet_pton
from typing import Optional

from python_socks.async_.asyncio import Proxy


class LocalTCP(Protocol):
    STAGE_NEGOTIATE = 0
    STAGE_CONNECT = 1
    STAGE_DESTROY = -1

    def __init__(self, config: dict) -> None:
        '''Create '''
        self.stage: int = None
        self.config: dict = config

        self.transport: AIOSST = None
        self.remote_tcp: RemoteTCP = None
        self.stream_reader: StreamReader = StreamReader()

        self.negotiate_task = None
        self.is_closing: bool = False

    def write(self, data: bytes) -> None:
        ''' Write data to transport
        :param data: bytes - data for write to transport'''

        if not self.transport.is_closing():
            self.transport.write(data)

    def connection_made(self, transport: AIOSST) -> None:
        self.transport = transport
        self.stream_reader.set_transport(transport)

        loop = get_event_loop()

        self.negotiate_task = loop.create_task(self.negotiate())
        self.stage = self.STAGE_NEGOTIATE

    def _addr_family(self, host: str) -> int:
        '''Detect destanation address family IPv4/IPv6/Domain

        :param host: str - destanation host'''
        try:
            inet_pton(AF_INET, host)
            return 1
        except OSError:
            try:
                inet_pton(AF_INET6, host)
                return 4
            except OSError:
                return 3

    def socks_reply(
        self,
        rep: int,
        bind_host: str = "0.0.0.0",
        bind_port: int = 0,
    ) -> bytes:
        '''Generate reply for negotiation
        :param rep: int - reply code
        :param bind_host: str - bind host
        :param bind_port: str - bind port'''

        VER, RSV = b"\x05", b"\x00"
        ATYP = self._addr_family(bind_host)

        if ATYP == 1:
            BND_ADDR = inet_pton(AF_INET, bind_host)
        elif ATYP == 4:
            BND_ADDR = inet_pton(AF_INET6, bind_host)
        else:
            BND_ADDR = len(bind_host).to_bytes(2, "big") + bind_host.encode("UTF-8")

        REP = rep.to_bytes(1, "big")
        ATYP = ATYP.to_bytes(1, "big")
        BND_PORT = int(bind_port).to_bytes(2, "big")

        return VER + REP + RSV + ATYP + BND_ADDR + BND_PORT

    async def connect(self, dst_addr: str, dst_port: int) -> None:
        '''Create connection to destanation host&port via proxy
        :param dst_addr: str - destanation host
        :param dst_port: int - destanation port'''

        try:
            sock = await Proxy.from_url(self.config['PROXY']).connect(
                dest_host=dst_addr, dest_port=dst_port
            )

            loop = get_event_loop()
            task = loop.create_connection(
                lambda: RemoteTCP(self, self.config), sock=sock
            )
            remote_tcp_transport, remote_tcp = await wait_for(task, 5)
        except ConnectionRefusedError:
            self.transport.write(self.socks_reply(5))
            raise ConnectionError
        except gaierror:
            self.transport.write(self.socks_reply(4))
            raise ConnectionError
        except Exception:
            self.transport.write(self.socks_reply(1))
            raise ConnectionError
        else:
            self.remote_tcp = remote_tcp
            bind_addr, bind_port = remote_tcp_transport.get_extra_info(
                "sockname"
            )
            self.transport.write(
                self.socks_reply(0, bind_addr, bind_port)
            )
            self.stage = self.STAGE_CONNECT

    async def get_dst_addr(self, dst_addr_type: int) -> str:
        if dst_addr_type == 1:
            dst_addr = inet_ntop(AF_INET, await self.stream_reader.readexactly(4))
        elif dst_addr_type == 3:
            domain_len = int.from_bytes(
                await self.stream_reader.readexactly(1), "big"
            )
            dst_addr = (await self.stream_reader.readexactly(domain_len)).decode()
        elif dst_addr_type == 4:
            dst_addr = inet_ntop(AF_INET6, await self.stream_reader.readexactly(16))
        else:
            self.transport.write(self.socks_reply(8))
            raise ValueError

        return dst_addr

    async def negotiate(self) -> None:
        """Negotiate with the client. Find more detail in RFC1928"""

        try:
            VER, NMETHODS = await self.stream_reader.readexactly(2)
            assert VER == 5, "Unsupported socks version"

            await self.stream_reader.readexactly(NMETHODS)
            self.transport.write(b"\x05" + int(0).to_bytes(1, "big"))

            VER, CMD, RSV, ATYP = await self.stream_reader.readexactly(4)
            assert CMD == 1, "Unsupported method. TCP only."

            dst_addr = await self.get_dst_addr(ATYP)
            dst_port = int.from_bytes(await self.stream_reader.readexactly(2), "big")

            await self.connect(dst_addr, dst_port)
        except (ConnectionError, ValueError):
            self.close()
        except AssertionError:
            self.transport.write(b"\x05\xff")
            self.close()
        except Exception as e:
            print('Unexpected SOCKS Proxy Error:', e)
            self.transport.write(b"\x05\xff")
            self.close()

    def data_received(self, data):
        if self.stage == self.STAGE_NEGOTIATE:
            self.stream_reader.feed_data(data)
        elif self.stage == self.STAGE_CONNECT:
            self.remote_tcp.write(data)
        elif self.stage == self.STAGE_DESTROY:
            self.close()

    def eof_received(self) -> None:
        self.close()

    def pause_writing(self) -> None:
        try:
            self.remote_tcp.transport.pause_reading()
        except AttributeError:
            pass

    def resume_writing(self) -> None:
        self.remote_tcp.transport.resume_reading()

    def connection_lost(self, exc: Optional[Exception]) -> None:
        self.close()

    def close(self):
        ''' Close all active connection '''

        if self.is_closing:
            return

        self.stage = self.STAGE_DESTROY
        self.is_closing = True

        self.negotiate_task and self.negotiate_task.cancel()
        self.transport and self.transport.close()
        self.remote_tcp and self.remote_tcp.close()


class RemoteTCP(Protocol):
    def __init__(self, local_tcp: LocalTCP, config: dict) -> None:
        self.local_tcp: LocalTCP = local_tcp
        self.transport: AIOSST = None

        self.config: dict = config
        self.is_closing: bool = False

    def write(self, data: bytes) -> None:
        if not self.transport.is_closing():
            self.transport.write(data)

    def connection_made(self, transport: AIOSST) -> None:
        self.transport: AIOSST = transport

    def data_received(self, data: bytes) -> None:
        self.local_tcp.write(data)

    def eof_received(self) -> None:
        self.close()

    def pause_writing(self) -> None:
        try:
            self.local_tcp.transport.pause_reading()
        except AttributeError:
            pass

    def resume_writing(self) -> None:
        self.local_tcp.transport.resume_reading()

    def connection_lost(self, _) -> None:
        self.close()

    def close(self) -> None:
        if self.is_closing:
            return

        self.is_closing = True
        self.transport and self.transport.close()
        self.local_tcp.close()
