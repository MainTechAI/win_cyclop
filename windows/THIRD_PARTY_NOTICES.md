# Third-party notices

Cyclop for Windows adapts the design and notch geometry of Cyclop:

- https://github.com/akalikbergenov/cyclop
- Copyright (c) 2026 akalikbergenov
- MIT License; see the repository's LICENSE (included as LICENSE.txt in portable builds).

Runtime dependencies retain their own licenses:

| Dependency | License | Project |
|---|---|---|
| PySide6 / Qt / Shiboken | LGPLv3/GPLv3 or commercial, as applicable to each distributed module | https://www.qt.io/licensing/open-source-lgpl-obligations |
| Python | PSF License | https://docs.python.org/3/license.html |
| PyWinRT | MIT | https://github.com/pywinrt/pywinrt |
| icalendar | BSD-2-Clause | https://github.com/collective/icalendar |
| recurring-ical-events | LGPL-3.0 | https://github.com/niccokunzmann/python-recurring-ical-events |
| x-wr-timezone | LGPL-3.0 | https://github.com/niccokunzmann/python-x-wr-timezone |
| python-dateutil | Apache-2.0 / BSD-3-Clause | https://github.com/dateutil/dateutil |
| tzdata | Apache-2.0 (code), public domain (IANA data) | https://github.com/python/tzdata |
| Argos Translate (optional, source installs) | MIT / CC0 | https://github.com/argosopentech/argos-translate |
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| python-sounddevice / PortAudio | MIT | https://github.com/spatialaudio/python-sounddevice |
| pycaw | MIT | https://github.com/AndreMiras/pycaw |
| comtypes | MIT | https://github.com/enthought/comtypes |
| nvidia-ml-py | BSD-3-Clause | https://pypi.org/project/nvidia-ml-py/ |
| faster-whisper / CTranslate2 | MIT | https://github.com/SYSTRAN/faster-whisper |
| Whisper model weights (downloaded on first use) | MIT | https://github.com/openai/whisper |
| PyAV / FFmpeg (bundled with faster-whisper) | BSD-3-Clause / LGPL-2.1+ | https://github.com/PyAV-Org/PyAV |
| Hugging Face Hub, tokenizers | Apache-2.0 | https://github.com/huggingface |
| ONNX Runtime (bundled with faster-whisper) | MIT | https://github.com/microsoft/onnxruntime |
| Wiktionary definitions (fetched at runtime, not bundled) | CC BY-SA 4.0 | https://en.wiktionary.org/wiki/Wiktionary:Copyrights |

The portable application uses a directory layout rather than embedding Qt into a single executable; Qt libraries remain separate. Do not remove dependency license files when redistributing. Any optional translation models and their additional dependencies carry their own licenses; inspect the selected model's package before redistribution. No music artwork or the upstream promotional screenshot is bundled with the Windows application.

The build records its installed package versions in BUILD-DEPENDENCIES.txt. Source is available in this repository; Qt/PySide source is available from the Qt project and https://code.qt.io/. Users may replace LGPL-covered libraries with compatible modified versions and reverse-engineer for debugging those modifications as provided by their licenses.
