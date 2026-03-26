
import asyncio
import can
import argparse
import os
import time
from pathlib import Path

# Address ranges for app slots, from can_bldr_summary.md and can_protocol.h
APP_A_START = 0x6000
APP_A_END = 0x13000
APP_B_START = 0x13000
APP_B_END = 0x20000
APP_IMG_MAX_DATA = 0xCFF8  # APP_IMG_SZ - 8 bytes reserved for CRC metadata

# From CAN_BLDR_SUMMARY.md and can_protocol.h
CMD_ID  = 0x300
DATA_ID = 0x301
RESP_ID = 0x302

CMD_PING = 0x01
CMD_START_UL = 0x02
CMD_RUN_APP = 0x05
CMD_GET_STATUS = 0x06
CMD_RESET = 0x07

RESP_ACK = 0x01
RESP_NAK = 0x02
RESP_READY = 0x03
RESP_ERROR = 0x05
RESP_CRC_OK = 0x06

RESP_NAMES = {
    RESP_ACK: "ACK",
    RESP_NAK: "NAK",
    RESP_READY: "READY",
    RESP_ERROR: "ERROR",
    RESP_CRC_OK: "CRC_OK",
}

BL_STATE_NAMES = {
    0: "IDLE",
    1: "READY",
    2: "RECEIVING",
    3: "VERIFYING",
    4: "ERROR",
}


class Log:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    LT_YELLOW = "\033[93m"
    LT_BLUE = "\033[94m"
    PINK = "\033[95m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BACKGROUND_LT_BLUE = "\033[104m"
    BACKGROUND_LT_GREEN = "\033[102m"
    BACKGROUND_LT_YELLOW = "\033[103m"
    BACKGROUND_LT_GRAY = "\033[47m"
    
    @staticmethod
    def step(message):
        print(f"{Log.BOLD}{Log.CYAN}{message}{Log.RESET}")

    @staticmethod
    def info(message):
        print(message)

    @staticmethod
    def txrx(message):
        print(f"{Log.PINK}{message}{Log.RESET}")

    @staticmethod
    def debug(message):
        print(f"{Log.CYAN}{message}{Log.RESET}")

    @staticmethod
    def stat(message):
        print(f"{Log.LT_YELLOW}{message}{Log.RESET}")
    
    @staticmethod
    def progress(message):
        print(f"{Log.BACKGROUND_LT_GRAY}{Log.BLUE}{message}{Log.RESET}")

    @staticmethod
    def success(message):
        print(f"{Log.GREEN}{message}{Log.RESET}")

    @staticmethod
    def warn(message):
        print(f"{Log.YELLOW}{message}{Log.RESET}")

    @staticmethod
    def error(message):
        print(f"{Log.RED}{message}{Log.RESET}")


class CanLoader:
    def __init__(self, channel, interface, bitrate):
        self.bus = can.interface.Bus(channel=channel, interface=interface, bitrate=bitrate)
        self.reader = can.AsyncBufferedReader()
        self.notifier = can.Notifier(self.bus, [self.reader])
        self.loop = asyncio.get_event_loop()

    async def send_cmd(self, cmd, data=None):
        payload = [cmd]
        if data:
            payload.extend(data)
        message = can.Message(arbitration_id=CMD_ID, data=payload, is_extended_id=False)
        self.bus.send(message)
        Log.txrx(f"Sent cmd : {self.format_can_message(message)}")

    @staticmethod
    def format_can_message(message):
        data_hex = " ".join(f"{byte:02X}" for byte in message.data)
        frame_type = "EXT" if message.is_extended_id else "STD"
        return (
            f"id=0x{message.arbitration_id:X} ({frame_type}), "
            f"dlc={message.dlc}, data=[{data_hex}]"
        )

    async def wait_for_bootloader_message(self, timeout=2.0, log_response=True, log_timeout=True):
        try:
            while True:
                msg = await asyncio.wait_for(self.reader.get_message(), timeout)
                if msg.arbitration_id == RESP_ID:
                    if log_response:
                        Log.txrx(f"Recv resp: {self.format_can_message(msg)}")
                    resp_code = msg.data[0]
                    payload = msg.data[1:] if len(msg.data) > 1 else None
                    return resp_code, payload
        except asyncio.TimeoutError:
            if log_timeout:
                Log.error("Timeout waiting for bootloader response")
            return None, None

    async def wait_for_response(self, expected_resp, timeout=2.0, log_response=True):
        resp_code, payload = await self.wait_for_bootloader_message(
            timeout=timeout,
            log_response=log_response,
        )
        if resp_code is None:
            Log.error(f"Timeout waiting for response {expected_resp}")
            return False, None
        if resp_code == expected_resp:
            return True, payload

        Log.error(f"Error: Expected response {expected_resp}, but got {resp_code}")
        return False, payload

    @staticmethod
    def parse_status_payload(payload):
        if not payload or len(payload) < 4:
            return None

        return {
            "state": payload[0],
            "bytes_received": payload[1] | (payload[2] << 8) | (payload[3] << 16),
        }

    @staticmethod
    def format_transfer_stats(bytes_sent, packets_sent, elapsed_seconds):
        if elapsed_seconds <= 0:
            return (
                f"Transfer stats: time={elapsed_seconds:.3f}s, bytes_sent={bytes_sent}, "
                f"packets_sent={packets_sent}, avg_rate=n/a"
            )

        avg_bytes_per_sec = bytes_sent / elapsed_seconds
        avg_packets_per_sec = packets_sent / elapsed_seconds
        return (
            f"Transfer stats: time={elapsed_seconds:.3f}s, bytes_sent={bytes_sent}, "
            f"packets_sent={packets_sent}, avg_rate={avg_bytes_per_sec:.1f} B/s, "
            f"avg_packets={avg_packets_per_sec:.1f} pkt/s"
        )

    @staticmethod
    def format_host_metrics(
        timeout_count,
        nak_count,
        grace_wait_count,
        fallback_count,
        peak_in_flight,
        recovery_seconds,
    ):
        return (
            f"Host metrics: peak_in_flight={peak_in_flight}, timeouts={timeout_count}, "
            f"naks={nak_count}, grace_waits={grace_wait_count}, "
            f"fallback_events={fallback_count}, "
            f"recovery_time={recovery_seconds:.3f}s"
        )

    @staticmethod
    def resolve_seq_to_index(seq_value, lower_bound, upper_bound):
        if lower_bound > upper_bound:
            return None

        candidate = seq_value
        if candidate < lower_bound:
            wraps = (lower_bound - candidate + 255) // 256
            candidate += wraps * 256

        if candidate > upper_bound:
            return None

        return candidate

    @staticmethod
    def compute_flow_grace_timeout(ack_timeout, ack_interval):
        return max(ack_timeout, min(0.05, ack_interval * 0.001))

    async def check_final_state(self, attempts=5, delay=0.2):
        Log.step("Checking bootloader state...")
        for attempt in range(1, attempts + 1):
            await self.send_cmd(CMD_GET_STATUS)
            resp_code, payload = await self.wait_for_bootloader_message(timeout=1.0)
            if resp_code is None:
                Log.warn(f"State check {attempt}/{attempts}: no response")
            else:
                resp_name = RESP_NAMES.get(resp_code, f"0x{resp_code:02X}")
                status = self.parse_status_payload(payload)
                if status is not None:
                    state_name = BL_STATE_NAMES.get(status["state"], f"UNKNOWN({status['state']})")
                    Log.info(
                        f"State check {attempt}/{attempts}: response={resp_name}, "
                        f"state={state_name}, bytes_received={status['bytes_received']}"
                    )
                elif payload:
                    payload_bytes = list(payload)
                    Log.info(
                        f"State check {attempt}/{attempts}: response={resp_name}, "
                        f"payload={payload_bytes}"
                    )
                else:
                    Log.info(f"State check {attempt}/{attempts}: response={resp_name}, no payload")
                return resp_code, payload

            if attempt < attempts:
                await asyncio.sleep(delay)

        return None, None

    async def upload_file(self, file_path, slot, window_size=1, ack_interval=1, ack_timeout=0.05):
        file_path = Path(file_path)
        if not file_path.is_file():
            Log.error(f"Error: File not found at {file_path}")
            return

        if file_path.suffix.lower() != ".bin":
            Log.error(f"Error: expected a raw .bin image, got '{file_path.suffix}'.")
            return

        file_size = os.path.getsize(file_path)
        Log.info(f"File: {file_path}, Size: {file_size} bytes")

        if file_size == 0 or file_size > APP_IMG_MAX_DATA:
            Log.error(
                f"Error: file size {file_size} is out of range. "
                f"Allowed: 1..{APP_IMG_MAX_DATA} bytes."
            )
            return

        with open(file_path, "rb") as f:
            header = f.read(8)
        if len(header) < 8:
            Log.error("Error: file is too small to contain vector table header.")
            return

        initial_sp = int.from_bytes(header[0:4], "little")
        reset_vector = int.from_bytes(header[4:8], "little")
        Log.info(f"Vector header: SP=0x{initial_sp:08x}, Reset=0x{reset_vector:08x}")

        if slot == 0:
            slot_start, slot_end = APP_A_START, APP_A_END
            slot_name = "App A"
        else:
            slot_start, slot_end = APP_B_START, APP_B_END
            slot_name = "App B"

        if not (slot_start <= reset_vector < slot_end):
            Log.error(
                f"Error: reset vector 0x{reset_vector:08x} is not in {slot_name} "
                f"range [0x{slot_start:08x}, 0x{slot_end:08x})."
            )
            Log.warn("Hint: build the app for the selected slot base address.")
            return

        # 0. Send 0xB007B007 to application to do a soft reset.
        Log.step("Sending soft reset command ...")
        await self.send_cmd(0xB0, [0x07, 0xB0, 0x07, 0xF0, 0xCA, 0xCC, 0x1A])
        await asyncio.sleep(0.05)
        
        # 1. Ping bootloader
        Log.step("Pinging bootloader...")
        await self.send_cmd(CMD_PING)
        success, _ = await self.wait_for_response(RESP_ACK)
        if not success:
            Log.error("Bootloader did not respond to PING.")
            return

        # 2. Start Upload
        Log.step("Sending START_UL command...")
        # Bootloader expects 24-bit size in pData[2..4].
        # send_cmd prepends CMD byte automatically.
        start_ul_data = [slot] + list(file_size.to_bytes(3, "little"))
        flow_mode = (window_size > 1) or (ack_interval > 1)
        if flow_mode:
            start_ul_data.extend([window_size & 0xFF, ack_interval & 0xFF])

        await self.send_cmd(CMD_START_UL, start_ul_data)
        success, _ = await self.wait_for_response(RESP_READY)
        if not success:
            Log.error("Bootloader did not respond with READY.")
            return

        if flow_mode:
            Log.info(
                f"Flow control enabled: window={window_size}, ack_interval={ack_interval}, "
                f"ack_timeout={ack_timeout:.3f}s"
            )
        else:
            Log.info("Legacy transfer mode: stop-and-wait ACK per packet")

        # 3. Send file data
        Log.step(f"Sending file data: {file_size} bytes")
        with open(file_path, "rb") as f:
            chunks = []
            while True:
                chunk = f.read(7)
                if not chunk:
                    break
                chunks.append(chunk)

        total_packets = len(chunks)
        oldest_unacked = 0
        next_to_send = 0
        furthest_sent = 0
        current_window = window_size
        bytes_sent = 0
        packets_sent = 0
        consecutive_timeouts = 0
        max_consecutive_timeouts = 30
        saw_crc_ok = False
        timeout_count = 0
        nak_count = 0
        grace_wait_count = 0
        fallback_count = 0
        peak_in_flight = 0
        recovery_start = None
        recovery_seconds = 0.0
        transfer_start = time.perf_counter()
        grace_wait_used = False

        while oldest_unacked < total_packets:
            while (next_to_send < total_packets) and ((next_to_send - oldest_unacked) < current_window):
                in_flight = next_to_send - oldest_unacked + 1
                peak_in_flight = max(peak_in_flight, in_flight)
                seq = next_to_send & 0xFF
                chunk = chunks[next_to_send]
                payload = [seq] + list(chunk)
                message = can.Message(arbitration_id=DATA_ID, data=payload, is_extended_id=False)
                self.bus.send(message)

                bytes_sent += len(chunk)
                packets_sent += 1
                if next_to_send % 500 == 0:
                    Log.progress(
                        f"Sent packet {next_to_send}/{total_packets - 1} "
                        f"(in_flight={next_to_send - oldest_unacked + 1})"
                    )
                next_to_send += 1
                furthest_sent = max(furthest_sent, next_to_send)

            wait_timeout = ack_timeout if next_to_send < total_packets else max(ack_timeout, 0.25)
            resp_code, payload = await self.wait_for_bootloader_message(
                timeout=wait_timeout,
                log_response=False,
                log_timeout=False,
            )

            in_flight_packets = next_to_send - oldest_unacked
            can_try_grace_wait = (
                resp_code is None
                and flow_mode
                and current_window > 1
                and in_flight_packets >= ack_interval
                and not grace_wait_used
            )
            if can_try_grace_wait:
                grace_wait_used = True
                grace_wait_count += 1
                grace_timeout = self.compute_flow_grace_timeout(ack_timeout, ack_interval)
                resp_code, payload = await self.wait_for_bootloader_message(
                    timeout=grace_timeout,
                    log_response=False,
                    log_timeout=False,
                )

            if resp_code is None:
                consecutive_timeouts += 1
                timeout_count += 1

                Log.warn(
                    "ACK timeout. Retransmitting from packet "
                    f"{oldest_unacked} (seq={oldest_unacked & 0xFF})."
                )
                # Congestion fallback: temporarily use stop-and-wait during recovery.
                if flow_mode:
                    if current_window != 1:
                        fallback_count += 1
                        if recovery_start is None:
                            recovery_start = time.perf_counter()
                    current_window = 1
                if consecutive_timeouts >= max_consecutive_timeouts:
                    Log.error(
                        "Too many consecutive ACK timeouts. "
                        "Aborting transfer to avoid endless retransmit loop."
                    )
                    return
                next_to_send = oldest_unacked
                grace_wait_used = False
                continue

            consecutive_timeouts = 0
            grace_wait_used = False

            if resp_code == RESP_ACK:
                if not payload or len(payload) < 1:
                    Log.warn("ACK without payload. Ignoring.")
                    continue

                if flow_mode and len(payload) >= 3:
                    prev_oldest_unacked = oldest_unacked
                    next_expected_seq = payload[0]
                    acked_up_to = self.resolve_seq_to_index(
                        next_expected_seq,
                        oldest_unacked,
                        furthest_sent,
                    )

                    if acked_up_to is None:
                        Log.warn(
                            "Cumulative ACK next_expected_seq out of range: "
                            f"{next_expected_seq}. Retransmitting from oldest unacked."
                        )
                        next_to_send = oldest_unacked
                        continue

                    if acked_up_to > oldest_unacked:
                        oldest_unacked = acked_up_to
                        next_to_send = max(next_to_send, oldest_unacked)
                        if oldest_unacked > prev_oldest_unacked:
                            if recovery_start is not None:
                                recovery_seconds += time.perf_counter() - recovery_start
                                recovery_start = None
                            current_window = window_size
                else:
                    ack_seq = payload[0]
                    expected_seq = oldest_unacked & 0xFF
                    if ack_seq != expected_seq:
                        Log.warn(
                            "ACK seq mismatch: expected "
                            f"{expected_seq}, got {ack_seq}. Retransmitting from oldest unacked."
                        )
                        next_to_send = oldest_unacked
                        continue

                    oldest_unacked += 1
                    if recovery_start is not None:
                        recovery_seconds += time.perf_counter() - recovery_start
                        recovery_start = None
                    current_window = window_size

            elif resp_code == RESP_NAK:
                nak_count += 1
                if payload and len(payload) >= 1:
                    expected_seq = payload[0]

                    # Tail completion edge case: all packets already sent, and receiver expects
                    # the next (not-yet-existent) sequence number. Treat transfer as accepted.
                    if (furthest_sent >= total_packets) and (expected_seq == (total_packets & 0xFF)):
                        Log.info(
                            "Receiver reports next expected seq beyond final packet; "
                            "treating transfer payload as fully received."
                        )
                        oldest_unacked = total_packets
                        continue

                    target_idx = self.resolve_seq_to_index(
                        expected_seq,
                        oldest_unacked,
                        furthest_sent,
                    )

                    if target_idx is None:
                        Log.warn(
                            f"NAK requested seq={expected_seq}, not in-flight. "
                            "Retransmitting from oldest unacked."
                        )
                        next_to_send = oldest_unacked
                    elif target_idx == furthest_sent:
                        Log.info(
                            f"Receiver requested resume from packet {target_idx} "
                            f"(seq={expected_seq}). Advancing send window."
                        )
                        oldest_unacked = target_idx
                        next_to_send = max(next_to_send, target_idx)
                        if recovery_start is not None:
                            recovery_seconds += time.perf_counter() - recovery_start
                            recovery_start = None
                        current_window = window_size
                    else:
                        Log.warn(
                            f"NAK received. Retransmitting from packet {target_idx} "
                            f"(seq={expected_seq})."
                        )
                        oldest_unacked = target_idx
                        next_to_send = target_idx
                        if current_window != 1:
                            fallback_count += 1
                            if recovery_start is None:
                                recovery_start = time.perf_counter()
                        current_window = 1
                else:
                    Log.warn("NAK without payload. Retransmitting from oldest unacked.")
                    next_to_send = oldest_unacked
                    if current_window != 1:
                        fallback_count += 1
                        if recovery_start is None:
                            recovery_start = time.perf_counter()
                    current_window = 1

            elif resp_code in (RESP_ERROR,):
                Log.error("Bootloader reported ERROR during transfer.")
                return

            elif resp_code == RESP_CRC_OK:
                # If transfer completion arrives early, accept and continue to final state check.
                saw_crc_ok = True
                oldest_unacked = total_packets

            else:
                Log.warn(f"Unexpected response during transfer: 0x{resp_code:02X}")

        transfer_elapsed = time.perf_counter() - transfer_start
        if recovery_start is not None:
            recovery_seconds += time.perf_counter() - recovery_start
        
        Log.success("File transfer completed.")
        Log.stat(self.format_transfer_stats(bytes_sent, packets_sent, transfer_elapsed))
        Log.stat(
            self.format_host_metrics(
                timeout_count,
                nak_count,
                grace_wait_count,
                fallback_count,
                peak_in_flight,
                recovery_seconds,
            )
        )

        if saw_crc_ok:
            Log.success("Upload process finished. Completion confirmed by CRC_OK.")
            return

        final_resp, final_payload = await self.check_final_state()
        if final_resp is None:
            Log.warn("Upload process finished, but the bootloader did not report a final state.")
        else:
            resp_name = RESP_NAMES.get(final_resp, f"0x{final_resp:02X}")
            status = self.parse_status_payload(final_payload)
            if status is not None:
                state_name = BL_STATE_NAMES.get(status["state"], f"UNKNOWN({status['state']})")
                Log.success(
                    "Upload process finished. Final bootloader state: "
                    f"{resp_name}, state={state_name}, "
                    f"bytes_received={status['bytes_received']}"
                )
                if status["bytes_received"] != file_size:
                    Log.warn(
                        "Warning: bootloader reported bytes_received="
                        f"{status['bytes_received']}, expected {file_size}."
                    )
            elif final_payload:
                Log.info(
                    "Upload process finished. Final bootloader state: "
                    f"{resp_name}, payload={list(final_payload)}"
                )
            else:
                Log.success(f"Upload process finished. Final bootloader state: {resp_name}")


    def close(self):
        self.notifier.stop()
        self.bus.shutdown()


async def main():
    parser = argparse.ArgumentParser(description="CAN bootloader host script for VA416xx.")
    parser.add_argument("file", help="Path to the binary file to upload.")
    parser.add_argument("--channel", default="can0", help="CAN channel (e.g., can0, vcan0).")
    parser.add_argument("--interface", default="socketcan", help="CAN bus type (e.g., socketcan, pcan, vector).")
    parser.add_argument("--bitrate", type=int, default=250000, help="CAN bitrate.")
    parser.add_argument("--slot", type=int, default=0, choices=[0, 1], help="Application slot (0 for App A, 1 for App B).")
    parser.add_argument(
        "--window-size",
        type=int,
        default=16,
        help="Flow-control window size (1..16). Use 1 for legacy stop-and-wait.",
    )
    parser.add_argument(
        "--ack-interval",
        type=int,
        default=16,
        help="Flow-control ACK interval (1..16, must be <= window-size).",
    )
    parser.add_argument(
        "--ack-timeout",
        type=float,
        default=0.01,
        help="Timeout in seconds while waiting for ACK/NAK before retransmit.",
    )
    
    args = parser.parse_args()

    if not (1 <= args.window_size <= 16):
        parser.error("--window-size must be in range 1..16")
    if not (1 <= args.ack_interval <= 16):
        parser.error("--ack-interval must be in range 1..16")
    if args.ack_interval > args.window_size:
        parser.error("--ack-interval must be <= --window-size")
    if args.ack_timeout <= 0:
        parser.error("--ack-timeout must be > 0")

    loader = CanLoader(channel=args.channel, interface=args.interface, bitrate=args.bitrate)
    
    try:
        await loader.upload_file(
            args.file,
            args.slot,
            window_size=args.window_size,
            ack_interval=args.ack_interval,
            ack_timeout=args.ack_timeout,
        )
    finally:
        loader.close()


if __name__ == "__main__":
    asyncio.run(main())
