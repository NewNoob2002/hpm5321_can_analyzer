#!/usr/bin/env python3
"""Dependency-free libusb bulk loopback tester for the Phase 0 probe."""

import argparse
import ctypes
import ctypes.util
import random
import sys
import time


VID = 0x34B7
PID = 0x1236
EP_OUT = 0x01
EP_IN = 0x81
INTERFACE = 0
DEVICE_OUT_WINDOW = 2048

LIBUSB_SUCCESS = 0
LIBUSB_ERROR_ACCESS = -3


def load_libusb() -> ctypes.CDLL:
    path = ctypes.util.find_library("usb-1.0")
    if not path:
        raise RuntimeError("libusb-1.0 runtime not found")
    lib = ctypes.CDLL(path)
    lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    lib.libusb_init.restype = ctypes.c_int
    lib.libusb_exit.argtypes = [ctypes.c_void_p]
    lib.libusb_open_device_with_vid_pid.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint16,
        ctypes.c_uint16,
    ]
    lib.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
    lib.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_claim_interface.restype = ctypes.c_int
    lib.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_release_interface.restype = ctypes.c_int
    lib.libusb_close.argtypes = [ctypes.c_void_p]
    lib.libusb_bulk_transfer.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ubyte,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
    ]
    lib.libusb_bulk_transfer.restype = ctypes.c_int
    lib.libusb_error_name.argtypes = [ctypes.c_int]
    lib.libusb_error_name.restype = ctypes.c_char_p
    return lib


def error_name(lib: ctypes.CDLL, code: int) -> str:
    value = lib.libusb_error_name(code)
    return value.decode() if value else f"libusb error {code}"


def transfer(
    lib: ctypes.CDLL,
    handle: ctypes.c_void_p,
    endpoint: int,
    data: bytes,
    timeout_ms: int,
) -> bytes:
    buffer = (ctypes.c_ubyte * len(data))()
    if endpoint == EP_OUT:
        buffer[:] = data
    transferred = ctypes.c_int()
    result = lib.libusb_bulk_transfer(
        handle,
        endpoint,
        buffer,
        len(buffer),
        ctypes.byref(transferred),
        timeout_ms,
    )
    if result != LIBUSB_SUCCESS:
        raise RuntimeError(
            f"endpoint 0x{endpoint:02x}: {error_name(lib, result)}"
        )
    if transferred.value != len(data):
        raise RuntimeError(
            f"endpoint 0x{endpoint:02x}: short transfer "
            f"{transferred.value}/{len(data)}"
        )
    return bytes(buffer[: transferred.value])


def terminate_hs_out_transfer(
    lib: ctypes.CDLL,
    handle: ctypes.c_void_p,
    payload_size: int,
    receive_window: int,
    timeout_ms: int,
) -> None:
    """Send a ZLP when a partial receive window ends on an HS packet boundary."""
    if payload_size >= receive_window or payload_size % 512 != 0:
        return
    dummy = (ctypes.c_ubyte * 1)()
    transferred = ctypes.c_int()
    result = lib.libusb_bulk_transfer(
        handle,
        EP_OUT,
        dummy,
        0,
        ctypes.byref(transferred),
        timeout_ms,
    )
    if result != LIBUSB_SUCCESS:
        raise RuntimeError(f"OUT ZLP: {error_name(lib, result)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--chunk", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=0x5321)
    parser.add_argument("--timeout-ms", type=int, default=3000)
    args = parser.parse_args()
    if args.bytes <= 0 or args.chunk <= 0:
        parser.error("--bytes and --chunk must be positive")

    lib = load_libusb()
    context = ctypes.c_void_p()
    result = lib.libusb_init(ctypes.byref(context))
    if result != LIBUSB_SUCCESS:
        print(f"FAIL libusb_init: {error_name(lib, result)}", file=sys.stderr)
        return 2

    handle = None
    claimed = False
    try:
        handle = lib.libusb_open_device_with_vid_pid(context, VID, PID)
        if not handle:
            print(
                "FAIL cannot open 34b7:1236; device absent or access denied. "
                "Install config/udev/99-hpm5321-can-analyzer.rules and reconnect.",
                file=sys.stderr,
            )
            return LIBUSB_ERROR_ACCESS

        result = lib.libusb_claim_interface(handle, INTERFACE)
        if result != LIBUSB_SUCCESS:
            print(
                f"FAIL claim interface 0: {error_name(lib, result)}",
                file=sys.stderr,
            )
            return result
        claimed = True

        rng = random.Random(args.seed)
        completed = 0
        started = time.monotonic()
        while completed < args.bytes:
            size = min(args.chunk, args.bytes - completed)
            payload = rng.randbytes(size)
            transfer(lib, handle, EP_OUT, payload, args.timeout_ms)
            terminate_hs_out_transfer(
                lib, handle, size, DEVICE_OUT_WINDOW, args.timeout_ms
            )
            echoed = transfer(lib, handle, EP_IN, bytes(size), args.timeout_ms)
            if echoed != payload:
                mismatch = next(
                    i for i, (expected, actual) in enumerate(zip(payload, echoed))
                    if expected != actual
                )
                print(
                    f"FAIL data mismatch at absolute byte {completed + mismatch}",
                    file=sys.stderr,
                )
                return 3
            completed += size

        elapsed = time.monotonic() - started
        mib_s = completed / (1024 * 1024) / elapsed
        print(
            f"PASS bytes={completed} chunk={args.chunk} seed={args.seed} "
            f"elapsed_s={elapsed:.3f} throughput_MiB_s={mib_s:.3f}"
        )
        return 0
    finally:
        if claimed:
            lib.libusb_release_interface(handle, INTERFACE)
        if handle:
            lib.libusb_close(handle)
        lib.libusb_exit(context)


if __name__ == "__main__":
    raise SystemExit(main())
