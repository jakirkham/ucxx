# SPDX-FileCopyrightText: Copyright (c) 2022-2025, NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: BSD-3-Clause

import asyncio
import multiprocessing as mp
import os
import struct

import numpy as np
import pytest

import ucxx
from ucxx._lib_async.utils import get_event_loop, hash64bits
from ucxx._lib_async.utils_test import compute_timeouts
from ucxx.testing import join_processes, terminate_process

mp = mp.get_context("spawn")


def _test_from_worker_address_server(queue, timeout):
    async def run():
        # Send worker address to client process via multiprocessing.Queue
        address = ucxx.get_worker_address()
        queue.put(address)

        # Receive address size
        address_size = np.empty(1, dtype=np.int64)
        await ucxx.recv(address_size, tag=0)

        # Receive address buffer on tag 0 and create UCXAddress from it
        remote_address = bytearray(address_size[0])
        await ucxx.recv(remote_address, tag=0)
        remote_address = ucxx.get_ucx_address_from_buffer(remote_address)

        # Create endpoint to remote worker using the received address
        ep = await ucxx.create_endpoint_from_worker_address(remote_address)

        # Send data to client's endpoint
        send_msg = np.arange(10, dtype=np.int64)
        await ep.send(send_msg, tag=1, force_tag=True)
        await ep.close()

    loop = get_event_loop()
    try:
        loop.run_until_complete(asyncio.wait_for(run(), timeout=timeout))
    finally:
        ucxx.stop_notifier_thread()

        loop.close()


def _test_from_worker_address_client(queue, timeout):
    async def run():
        # Read local worker address
        address = ucxx.get_worker_address()

        # Receive worker address from server via multiprocessing.Queue, create
        # endpoint to server
        remote_address = queue.get()
        ep = await ucxx.create_endpoint_from_worker_address(remote_address)

        # Send local address to server on tag 0
        await ep.send(np.array(address.length, np.int64), tag=0, force_tag=True)
        await ep.send(address, tag=0, force_tag=True)

        # Receive message from server
        recv_msg = np.empty(10, dtype=np.int64)
        await ep.recv(recv_msg, tag=1, force_tag=True)
        await ep.close()

        np.testing.assert_array_equal(recv_msg, np.arange(10, dtype=np.int64))

    loop = get_event_loop()
    try:
        loop.run_until_complete(asyncio.wait_for(run(), timeout=timeout))
    finally:
        ucxx.stop_notifier_thread()

        loop.close()


def test_from_worker_address(pytestconfig):
    async_timeout, join_timeout = compute_timeouts(pytestconfig)

    queue = mp.Queue()

    server = mp.Process(
        target=_test_from_worker_address_server,
        args=(queue, async_timeout),
    )
    server.start()

    client = mp.Process(
        target=_test_from_worker_address_client,
        args=(queue, async_timeout),
    )
    client.start()

    join_processes([client, server], timeout=join_timeout)
    terminate_process(client)
    terminate_process(server)


def _get_address_info(address=None):
    # Fixed frame size
    frame_size = 10000

    # Header format: Recv Tag (Q) + Send Tag (Q) + UCXAddress.length (Q)
    header_fmt = "QQQ"

    # Data length
    data_length = frame_size - struct.calcsize(header_fmt)

    # Padding length
    padding_length = None if address is None else (data_length - address.length)

    # Header + UCXAddress string + padding
    fixed_size_address_buffer_fmt = header_fmt + str(data_length) + "s"

    assert struct.calcsize(fixed_size_address_buffer_fmt) == frame_size

    return {
        "frame_size": frame_size,
        "data_length": data_length,
        "padding_length": padding_length,
        "fixed_size_address_buffer_fmt": fixed_size_address_buffer_fmt,
    }


def _pack_address_and_tag(address, recv_tag, send_tag):
    address_info = _get_address_info(address)

    fixed_size_address_packed = struct.pack(
        address_info["fixed_size_address_buffer_fmt"],
        recv_tag,  # Recv Tag
        send_tag,  # Send Tag
        address.length,  # Address buffer length
        (
            bytearray(address) + bytearray(address_info["padding_length"])
        ),  # Address buffer + padding
    )

    assert len(fixed_size_address_packed) == address_info["frame_size"]

    return fixed_size_address_packed


def _unpack_address_and_tag(address_packed):
    address_info = _get_address_info()

    recv_tag, send_tag, address_length, address_padded = struct.unpack(
        address_info["fixed_size_address_buffer_fmt"],
        address_packed,
    )

    # Swap send and recv tags, as they are used by the remote process in the
    # opposite direction.
    return {
        "address": address_padded[:address_length],
        "recv_tag": send_tag,
        "send_tag": recv_tag,
    }


def _test_from_worker_address_server_fixedsize(num_nodes, queue, timeout):
    async def run():
        async def _handle_client(packed_remote_address):
            # Unpack the fixed-size address+tag buffer
            unpacked = _unpack_address_and_tag(packed_remote_address)
            remote_address = ucxx.get_ucx_address_from_buffer(unpacked["address"])

            # Create endpoint to remote worker using the received address
            ep = await ucxx.create_endpoint_from_worker_address(remote_address)

            # Send data to client's endpoint
            send_msg = np.arange(10, dtype=np.int64)
            await ep.send(send_msg, tag=unpacked["send_tag"], force_tag=True)

            # Receive data from client's endpoint
            recv_msg = np.empty(20, dtype=np.int64)
            await ep.recv(recv_msg, tag=unpacked["recv_tag"], force_tag=True)

            np.testing.assert_array_equal(recv_msg, np.arange(20, dtype=np.int64))

        # Send worker address to client processes via multiprocessing.Queue,
        # one entry for each client.
        address = ucxx.get_worker_address()
        for i in range(num_nodes):
            queue.put(address)

        address_info = _get_address_info()

        server_tasks = []
        for i in range(num_nodes):
            # Receive fixed-size address+tag buffer on tag 0
            packed_remote_address = bytearray(address_info["frame_size"])
            await ucxx.recv(packed_remote_address, tag=0)

            # Create an async task for client
            server_tasks.append(_handle_client(packed_remote_address))

        # Await handling each client request
        await asyncio.gather(*server_tasks)

    loop = get_event_loop()
    try:
        loop.run_until_complete(asyncio.wait_for(run(), timeout=timeout))
    finally:
        ucxx.stop_notifier_thread()

        loop.close()


def _test_from_worker_address_client_fixedsize(queue, timeout):
    async def run():
        # Read local worker address
        address = ucxx.get_worker_address()
        recv_tag = hash64bits(os.urandom(16))
        send_tag = hash64bits(os.urandom(16))
        packed_address = _pack_address_and_tag(address, recv_tag, send_tag)

        # Receive worker address from server via multiprocessing.Queue, create
        # endpoint to server
        remote_address = queue.get()
        ep = await ucxx.create_endpoint_from_worker_address(remote_address)

        # Send local address to server on tag 0
        await ep.send(packed_address, tag=0, force_tag=True)

        # Receive message from server
        recv_msg = np.empty(10, dtype=np.int64)
        await ep.recv(recv_msg, tag=recv_tag, force_tag=True)

        np.testing.assert_array_equal(recv_msg, np.arange(10, dtype=np.int64))

        # Send message to server
        send_msg = np.arange(20, dtype=np.int64)
        await ep.send(send_msg, tag=send_tag, force_tag=True)

    loop = get_event_loop()
    try:
        loop.run_until_complete(asyncio.wait_for(run(), timeout=timeout))
    finally:
        ucxx.stop_notifier_thread()

        loop.close()


@pytest.mark.slow
@pytest.mark.parametrize("num_nodes", [1, 2, 4, 8])
def test_from_worker_address_multinode(pytestconfig, num_nodes):
    async_timeout, join_timeout = compute_timeouts(pytestconfig)

    queue = mp.Queue()

    server = mp.Process(
        target=_test_from_worker_address_server_fixedsize,
        args=(num_nodes, queue, async_timeout),
    )
    server.start()

    clients = []
    for i in range(num_nodes):
        client = mp.Process(
            target=_test_from_worker_address_client_fixedsize,
            args=(queue, async_timeout),
        )
        client.start()
        clients.append(client)

    join_processes(clients + [server], timeout=join_timeout)
    for client in clients:
        terminate_process(client)
    terminate_process(server)
