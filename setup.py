from setuptools import setup, find_packages

setup(
    name="bt-proxy",
    version="1.0.2",
    description="ESPHome-compatible Bluetooth Proxy",
    packages=find_packages(),
    install_requires=[
        "bleak>=0.21.0",
        "zeroconf>=0.80.0",
    ],
    entry_points={
        "console_scripts": [
            "bt-proxy=bt_proxy.__main__:main"
        ],
    },
)
