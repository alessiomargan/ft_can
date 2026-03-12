
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

RESP_NAMES = {
    RESP_ACK: "ACK",
    RESP_NAK: "NAK",
    RESP_READY: "READY",
    RESP_ERROR: "ERROR",
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
    def __init__(self, channel, bustype, bitrate):
        self.bus = can.interface.Bus(channel=channel, bustype=bustype, bitrate=bitrate)
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

    async def wait_for_bootloader_message(self, timeout=2.0, log_response=True):
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

    async def upload_file(self, file_path, slot):
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
        await self.send_cmd(CMD_START_UL, start_ul_data)
        success, _ = await self.wait_for_response(RESP_READY)
        if not success:
            Log.error("Bootloader did not respond with READY.")
            return

        # 3. Send file data
        Log.step(f"Sending file data: {file_size} bytes")
        with open(file_path, "rb") as f:
            seq = 0
            bytes_sent = 0
            packets_sent = 0
            transfer_start = time.perf_counter()
            while True:
                chunk = f.read(7)
                if not chunk:
                    break
                
                # Payload: [SEQ, DATA...]
                payload = [seq & 0xFF] + list(chunk)
                message = can.Message(arbitration_id=DATA_ID, data=payload, is_extended_id=False)
                self.bus.send(message)
                # A short sleep to avoid overwhelming the CAN bus buffer on the device
                #await asyncio.sleep(0.001) 
                
                # Data ACKs are frequent; keep timeout short and suppress per-packet logging.
                success, ack_data = await self.wait_for_response(
                    RESP_ACK,
                    timeout=0.005,
                    log_response=False,
                )
                if not success:
                    if ack_data and len(ack_data) > 0:
                        Log.error(
                            "Bootloader did not ACK data chunk "
                            f"seq={seq & 0xFF}. Last seq received={ack_data[0]}."
                        )
                    else:
                        Log.error(
                            "Bootloader did not ACK data chunk "
                            f"seq={seq & 0xFF}."
                        )
                    return

                # Some bootloaders echo the last accepted sequence in ACK payload byte 0.
                if ack_data and len(ack_data) > 0 and ack_data[0] != (seq & 0xFF):
                    Log.warn(
                        "Warning: ACK seq mismatch for data chunk "
                        f"seq={seq & 0xFF}, bootloader reported last seq={ack_data[0]}."
                    )
                
                if (seq % 500 == 0):
                    Log.progress(f"Sent packet {seq}...")

                bytes_sent += len(chunk)
                packets_sent += 1
                seq += 1

        transfer_elapsed = time.perf_counter() - transfer_start
        
        Log.success("File transfer completed.")
        Log.stat(self.format_transfer_stats(bytes_sent, packets_sent, transfer_elapsed))
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
    parser.add_argument("--bustype", default="socketcan", help="CAN bus type (e.g., socketcan, pcan, vector).")
    parser.add_argument("--bitrate", type=int, default=250000, help="CAN bitrate.")
    parser.add_argument("--slot", type=int, default=0, choices=[0, 1], help="Application slot (0 for App A, 1 for App B).")
    
    args = parser.parse_args()

    loader = CanLoader(channel=args.channel, bustype=args.bustype, bitrate=args.bitrate)
    
    try:
        await loader.upload_file(args.file, args.slot)
    finally:
        loader.close()


if __name__ == "__main__":
    asyncio.run(main())
