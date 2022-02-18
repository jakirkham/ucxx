import numpy as np

from ucxx._lib.arr import Array
import ucxx._lib.libucxx as ucx_api


def main():
    ctx = ucx_api.UCXContext()

    worker = ucx_api.UCXWorker(ctx)

    worker.startProgressThread()

    wireup_send_buf = np.arange(3)
    wireup_recv_buf = np.empty_like(wireup_send_buf)
    send_bufs = [
        np.arange(50),
        np.arange(500),
        np.arange(50000),
    ]
    recv_bufs = [np.empty_like(b) for b in send_bufs]

    global listener_ep, callback_finished
    listener_ep = None
    callback_finished = False

    def listener_callback(conn_request):
        global listener_ep, callback_finished
        listener_ep = listener.createEndpointFromConnRequest(conn_request, True)
        callback_finished = True

    listener = ucx_api.UCXListener.create(worker, 12345, listener_callback,)

    ep = ucx_api.UCXEndpoint.create(
        worker, "127.0.0.1", 12345, endpoint_error_handling=True,
    )

    while listener_ep is None:
        pass

    wireup_recv_req = ep.tag_send(Array(wireup_send_buf), tag=0)
    wireup_send_req = listener_ep.tag_recv(Array(wireup_recv_buf), tag=0)

    while not wireup_recv_req.is_ready() or not wireup_send_req.is_ready():
        pass

    np.testing.assert_equal(wireup_recv_buf, wireup_send_buf)

    requests = [
        listener_ep.tag_send(Array(send_bufs[0]), tag=0),
        listener_ep.tag_send(Array(send_bufs[1]), tag=1),
        listener_ep.tag_send(Array(send_bufs[2]), tag=2),
        ep.tag_recv(Array(recv_bufs[0]), tag=0),
        ep.tag_recv(Array(recv_bufs[1]), tag=1),
        ep.tag_recv(Array(recv_bufs[2]), tag=2),
    ]
    while not all(r.is_ready() for r in requests):
        pass

    while callback_finished is not True:
        pass

    worker.stopProgressThread()

    for recv_buf, send_buf in zip(recv_bufs, send_bufs):
        np.testing.assert_equal(recv_buf, send_buf)


main()
