from setuptools import setup, find_packages

setup(
    name="blinky-assistant-holo-device",
    version="0.1",
    package_dir={"": "pkg"},
    packages=[
        "alarm_handler",
        "animations",
        "audio",
        "hologram_fans",
        "log",
        "web",
    ],
    install_requires=[
        "websockets",
        "requests",
        "psutil",
        "soundfile",
        "sounddevice",
        "numpy",
	    "scipy",
        "webrtcvad; platform_system != 'Windows'",          # not available on Windows
        "webrtcvad-wheels; platform_system == 'Windows'",   # workaround for Windows
    ],
)
