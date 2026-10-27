"""Check native projections with the same apartment lifetime as MediaWorker."""
from concurrent.futures import ThreadPoolExecutor


def check_projection():
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
    from winrt.windows.storage.streams import Buffer

    assert callable(GlobalSystemMediaTransportControlsSessionManager.request_async)
    buffer = Buffer(8)
    buffer.length = 8
    assert len(bytes(buffer)) == 8
    # Text capture (image → text) projections.
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.globalization import Language
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    assert callable(BitmapDecoder.create_async) and BitmapPixelFormat.BGRA8 is not None
    assert SoftwareBitmap is not None and DataWriter is not None and InMemoryRandomAccessStream is not None
    languages = [language.language_tag for language in OcrEngine.available_recognizer_languages]
    print("OCR languages:", ", ".join(languages) or "none installed")
    assert Language("en-US").language_tag
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
    print("Windows Runtime imports, buffer and OCR projections, and worker shutdown OK")
