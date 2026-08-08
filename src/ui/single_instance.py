"""Qt local-server based single-instance activation for FileOps Hub."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceController(QObject):
    activation_requested = pyqtSignal()

    def __init__(self, server_name: str):
        super().__init__()
        self.server_name = server_name
        self.server = QLocalServer(self)
        self._pending_sockets = set()
        self.server.newConnection.connect(self._accept_connections)

    @classmethod
    def acquire(cls, server_name: str, *, show_existing: bool = True):
        """Return a controller for the primary instance, otherwise notify it."""

        probe = QLocalSocket()
        probe.connectToServer(server_name)
        if probe.waitForConnected(250):
            probe.write(b"show" if show_existing else b"wake")
            probe.waitForBytesWritten(250)
            probe.waitForReadyRead(500)
            probe.disconnectFromServer()
            return None

        controller = cls(server_name)
        QLocalServer.removeServer(server_name)
        if not controller.server.listen(server_name):
            raise RuntimeError(controller.server.errorString())
        return controller

    def _accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            self._pending_sockets.add(socket)
            socket.readyRead.connect(lambda current=socket: self._read_request(current))
            socket.disconnected.connect(lambda current=socket: self._discard_socket(current))
            if socket.bytesAvailable():
                self._read_request(socket)

    def _read_request(self, socket):
        request = bytes(socket.readAll()).strip().lower()
        if request == b"show":
            self.activation_requested.emit()
        socket.write(b"ok")
        socket.flush()
        socket.disconnectFromServer()

    def _discard_socket(self, socket):
        self._pending_sockets.discard(socket)
        socket.deleteLater()

    def close(self):
        self.server.close()
        QLocalServer.removeServer(self.server_name)
