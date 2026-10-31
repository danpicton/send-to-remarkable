"""Keep async tests runnable in seccomp sandboxes that deny socketpair.send.

CPython's threaded child watcher and thread pool wake the event loop through a
local socket pair. Some offline coding sandboxes permit socket creation but deny
send(), even locally. A timer lets the loop observe their completed callbacks.
This fixture changes no application result, clock, process, timeout or network mock.
It is inactive on ordinary hosts.
"""

import asyncio
import socket

import pytest_asyncio


def self_pipe_blocked():
    sender, receiver = socket.socketpair()
    try:
        sender.send(b"x")
        return False
    except PermissionError:
        return True
    finally:
        sender.close()
        receiver.close()


SELF_PIPE_BLOCKED = self_pipe_blocked()


@pytest_asyncio.fixture(autouse=True)
async def sandbox_event_loop_wakeup():
    if not SELF_PIPE_BLOCKED:
        yield
        return

    loop = asyncio.get_running_loop()

    def pulse():
        loop.call_later(0.01, pulse)

    # Keep waking through Runner's thread-pool shutdown too. loop.close() clears
    # the remaining timer; there is no background task or live thread to retain.
    pulse()
    yield
