"""Check native projections with the same apartment lifetime as MediaWorker."""
from concurrent.futures import ThreadPoolExecutor


def check_projection():
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
    from winrt.windows.storage.streams import Buffer

    assert callable(GlobalSystemMediaTransportControlsSessionManager.request_async)
    buffer = Buffer(8)
    buffer.length = 8
    assert len(bytes(buffer)) == 8
    # All projected instances leave scope before COM is uninitialized.


def check_worker():
    from winrt.runtime import ApartmentType, init_apartment, uninit_apartment

    init_apartment(ApartmentType.MULTI_THREADED)
    try:
        check_projection()
    finally:
        uninit_apartment()


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(check_worker).result(timeout=15)
    print("Windows Runtime imports, buffer projection and worker shutdown OK")
