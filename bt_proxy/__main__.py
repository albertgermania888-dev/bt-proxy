"""Main entry point for the Bluetooth Proxy."""

from __future__ import annotations

import sys
import argparse
import json
import os
import asyncio
import logging
import signal
import socket
import subprocess

from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from . import EMULATED_ESPHOME_VERSION
from .api_server import APIServer
from .ble_manager import BLEManager

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Get the primary local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"



async def register_mdns(
    name: str, port: int, mac: str
) -> tuple[AsyncZeroconf, AsyncServiceInfo]:
    """Register the service via mDNS so Home Assistant can discover it."""
    local_ip = get_local_ip()
    logger.info("Advertising mDNS on %s:%d", local_ip, port)

    # ESPHome devices advertise as _esphomelib._tcp.local.
    info = AsyncServiceInfo(
        "_esphomelib._tcp.local.",
        f"{name}._esphomelib._tcp.local.",
        addresses=[socket.inet_aton(local_ip)],
        port=port,
        properties={
            "version": EMULATED_ESPHOME_VERSION,
            "mac": mac.replace(":", "").lower(),
            "platform": "linux",
            "network": "wifi",
            "api_encryption": "",
        },
        server=f"{name}.local.",
    )

    zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    await zc.async_register_service(info)
    return zc, info


async def async_main(args: argparse.Namespace) -> None:
    """Async main entry point."""
    bt_mac = args.mac_address
    if not bt_mac:
        logger.error("No MAC address configured. Please set 'mac_address' in /etc/bt-proxy.json.")
        sys.exit(1)

    logger.info("Bluetooth MAC: %s", bt_mac)

    ble_manager = BLEManager(
        max_connections=args.max_connections,
        adapter=args.adapter,
    )

    server = APIServer(
        ble_manager=ble_manager,
        name=args.name,
        friendly_name=args.friendly_name,
        manufacturer=args.manufacturer,
        model=args.model,
        mac_address=bt_mac,
        bt_mac_address=bt_mac,
        port=args.port,
    )

    # Register mDNS
    zc, service_info = await register_mdns(args.name, args.port, bt_mac)

    # Start BLE scanning
    await ble_manager.start_scanning()

    # Start API server
    await server.start()

    # Wait for shutdown signal
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("Bluetooth Proxy '%s' is running", args.name)
    await stop_event.wait()

    # Cleanup
    logger.info("Shutting down...")
    await server.stop()
    await ble_manager.cleanup()
    await zc.async_unregister_service(service_info)
    await zc.async_close()
    logger.info("Shutdown complete")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ESPHome-compatible Bluetooth Proxy"
    )
    parser.add_argument(
        "--name",
        help="Device name (default: bt-proxy)",
    )
    parser.add_argument(
        "--friendly-name",
        help="Friendly name (default: Bluetooth Proxy)",
    )
    parser.add_argument(
        "--manufacturer",
        help="Manufacturer name (default: OpenLumi)",
    )
    parser.add_argument(
        "--model",
        help="Model name (default: Xiaomi Gateway)",
    )
    parser.add_argument(
        "--mac-address",
        help="MAC address (default: 38:83:9A:68:D5:8F)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="API server port (default: 6053)",
    )
    parser.add_argument(
        "--max-connections",
        type=int,
        help="Max concurrent BLE connections (default: 3)",
    )
    parser.add_argument(
        "--adapter",
        default=None,
        help="Bluetooth adapter (e.g. hci0). Uses default if not specified.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    # OpenWrt Config File Support
    config_path = "/etc/bt-proxy.json"
    default_config = {
        "name": "bt-proxy",
        "friendly_name": "Bluetooth Proxy",
        "manufacturer": "OpenLumi",
        "model": "Xiaomi Gateway",
        "mac_address": "38:83:9A:68:D5:8F",
        "port": 6053,
        "max_connections": 3,
        "log_level": "INFO"
    }

    if not os.path.exists(config_path):
        try:
            with open(config_path, "w") as f:
                json.dump(default_config, f, indent=4)
            logger.info("Created default config at %s", config_path)
        except Exception as e:
            logger.warning("Could not create default config at %s: %s", config_path, e)

    loaded_config = default_config.copy()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                loaded_config.update(json.load(f))
        except Exception as e:
            logger.error("Failed to read config from %s: %s", config_path, e)

    parser.set_defaults(
        name=loaded_config.get("name", default_config["name"]),
        friendly_name=loaded_config.get("friendly_name", default_config["friendly_name"]),
        manufacturer=loaded_config.get("manufacturer", default_config["manufacturer"]),
        model=loaded_config.get("model", default_config["model"]),
        mac_address=loaded_config.get("mac_address", default_config["mac_address"]),
        port=loaded_config.get("port", default_config["port"]),
        max_connections=loaded_config.get("max_connections", default_config["max_connections"]),
        log_level=loaded_config.get("log_level", default_config["log_level"]),
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
