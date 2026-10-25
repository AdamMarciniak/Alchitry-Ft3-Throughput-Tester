"""Local file-queue client. No socket, remote access, or arbitrary command execution."""
import ctypes
import json
import os
from pathlib import Path
import time
import uuid
from rf_debug import atomic_json


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.restype = ctypes.c_void_p
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # denied means existence is uncertain
        try:
            code = ctypes.c_ulong()
            api.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
            return code.value == 259
        finally:
            api.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def server_info(directory):
    try:
        return json.loads((Path(directory) / 'server.json').read_text())
    except (OSError, ValueError):
        return {}


def server_alive(directory):
    info = server_info(directory)
    return info.get('state') != 'closed' and pid_alive(info.get('pid'))


def request(directory, body, timeout=60):
    directory = Path(directory).resolve()
    info = server_info(directory)
    if not server_alive(directory):
        raise RuntimeError('Bench host is not running')
    key = uuid.uuid4().hex
    payload = dict(body, id=key, server_id=info['server_id'],
                   created_unix=time.time(), ttl_s=timeout)
    atomic_json(directory / (key + '.request.json'), payload)
    response = directory / (key + '.response.json')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if response.is_file():
            result = json.loads(response.read_text())
            if not result.get('ok'):
                raise RuntimeError(result.get('error', 'Bench request failed'))
            return result.get('result')
        if not pid_alive(info['pid']):
            raise RuntimeError('Bench host exited during request')
        time.sleep(.05)
    raise TimeoutError(f"Bench request timed out: {body.get('op')}; inspect {directory}")
