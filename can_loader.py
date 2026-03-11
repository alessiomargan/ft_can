
import asyncio
import can
import argparse
import os
from pathlib import Path

APP_A_START = 0x6000
APP_A_END = 0x13000
APP_B_START = 0x13000
APP_B_END = 0x20000
APP_IMG_MAX_DATA = 0xCFF8  # APP_IMG_SZ - 8 bytes reserved for CRC metadata

# From CAN_BLDR_SUMMARY.md and can_protocol.h
CMD_ID = 0x200
DATA_ID = 0x201
RESP_ID = 0x202

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
        print(f"Sent command: {message}")

    async def wait_for_bootloader_message(self, timeout=2.0, log_response=True):
        try:
            while True:
                msg = await asyncio.wait_for(self.reader.get_message(), timeout)
                if msg.arbitration_id == RESP_ID:
                    if log_response:
                        print(f"Received response: {msg}")
                    resp_code = msg.data[0]
                    payload = msg.data[1:] if len(msg.data) > 1 else None
                    return resp_code, payload
        except asyncio.TimeoutError:
            print("Timeout waiting for bootloader response")
            return None, None

    async def wait_for_response(self, expected_resp, timeout=2.0, log_response=True):
        resp_code, payload = await self.wait_for_bootloader_message(
            timeout=timeout,
            log_response=log_response,
        )
        if resp_code is None:
            print(f"Timeout waiting for response {expected_resp}")
            return False, None
        if resp_code == expected_resp:
            return True, payload

        print(f"Error: Expected response {expected_resp}, but got {resp_code}")
        return False, payload

    @staticmethod
    def parse_status_payload(payload):
        if not payload or len(payload) < 4:
            return None

        return {
            "state": payload[0],
            "bytes_received": payload[1] | (payload[2] << 8) | (payload[3] << 16),
        }

    async def check_final_state(self, attempts=5, delay=0.2):
        print("Checking bootloader state...")
        for attempt in range(1, attempts + 1):
            await self.send_cmd(CMD_GET_STATUS)
            resp_code, payload = await self.wait_for_bootloader_message(timeout=1.0)
            if resp_code is None:
                print(f"State check {attempt}/{attempts}: no response")
            else:
                resp_name = RESP_NAMES.get(resp_code, f"0x{resp_code:02X}")
                status = self.parse_status_payload(payload)
                if status is not None:
                    state_name = BL_STATE_NAMES.get(status["state"], f"UNKNOWN({status['state']})")
                    print(
                        f"State check {attempt}/{attempts}: response={resp_name}, "
                        f"state={state_name}, bytes_received={status['bytes_received']}"
                    )
                elif payload:
                    payload_bytes = list(payload)
                    print(
                        f"State check {attempt}/{attempts}: response={resp_name}, "
                        f"payload={payload_bytes}"
                    )
                else:
                    print(f"State check {attempt}/{attempts}: response={resp_name}, no payload")
                return resp_code, payload

            if attempt < attempts:
                await asyncio.sleep(delay)

        return None, None

    async def upload_file(self, file_path, slot):
        file_path = Path(file_path)
        if not file_path.is_file():
            print(f"Error: File not found at {file_path}")
            return

        if file_path.suffix.lower() != ".bin":
            print(f"Error: expected a raw .bin image, got '{file_path.suffix}'.")
            return

        file_size = os.path.getsize(file_path)
        print(f"File: {file_path}, Size: {file_size} bytes")

        if file_size == 0 or file_size > APP_IMG_MAX_DATA:
            print(
                f"Error: file size {file_size} is out of range. "
                f"Allowed: 1..{APP_IMG_MAX_DATA} bytes."
            )
            return

        with open(file_path, "rb") as f:
            header = f.read(8)
        if len(header) < 8:
            print("Error: file is too small to contain vector table header.")
            return

        initial_sp = int.from_bytes(header[0:4], "little")
        reset_vector = int.from_bytes(header[4:8], "little")
        print(f"Vector header: SP=0x{initial_sp:08x}, Reset=0x{reset_vector:08x}")

        if slot == 0:
            slot_start, slot_end = APP_A_START, APP_A_END
            slot_name = "App A"
        else:
            slot_start, slot_end = APP_B_START, APP_B_END
            slot_name = "App B"

        if not (slot_start <= reset_vector < slot_end):
            print(
                f"Error: reset vector 0x{reset_vector:08x} is not in {slot_name} "
                f"range [0x{slot_start:08x}, 0x{slot_end:08x})."
            )
            print("Hint: build the app for the selected slot base address.")
            return

        # 1. Ping bootloader
        print("Pinging bootloader...")
        await self.send_cmd(CMD_PING)
        success, _ = await self.wait_for_response(RESP_ACK)
        if not success:
            print("Bootloader did not respond to PING.")
            return

        # 2. Start Upload
        print("Sending START_UL command...")
        # Bootloader expects 24-bit size in pData[2..4].
        # send_cmd prepends CMD byte automatically.
        start_ul_data = [slot] + list(file_size.to_bytes(3, "little"))
        await self.send_cmd(CMD_START_UL, start_ul_data)
        success, _ = await self.wait_for_response(RESP_READY)
        if not success:
            print("Bootloader did not respond with READY.")
            return

        # 3. Send file data
        print(f"Sending file data: {file_size} bytes")
        with open(file_path, "rb") as f:
            seq = 0
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
                        print(
                            "Bootloader did not ACK data chunk "
                            f"seq={seq & 0xFF}. Last seq received={ack_data[0]}."
                        )
                    else:
                        print(
                            "Bootloader did not ACK data chunk "
                            f"seq={seq & 0xFF}."
                        )
                    return

                # Some bootloaders echo the last accepted sequence in ACK payload byte 0.
                if ack_data and len(ack_data) > 0 and ack_data[0] != (seq & 0xFF):
                    print(
                        "Warning: ACK seq mismatch for data chunk "
                        f"seq={seq & 0xFF}, bootloader reported last seq={ack_data[0]}."
                    )
                
                if (seq % 500 == 0):
                    print(f"Sent packet {seq}...")

                seq += 1
        
        print("File transfer completed.")
        final_resp, final_payload = await self.check_final_state()
        if final_resp is None:
            print("Upload process finished, but the bootloader did not report a final state.")
        else:
            resp_name = RESP_NAMES.get(final_resp, f"0x{final_resp:02X}")
            status = self.parse_status_payload(final_payload)
            if status is not None:
                state_name = BL_STATE_NAMES.get(status["state"], f"UNKNOWN({status['state']})")
                print(
                    "Upload process finished. Final bootloader state: "
                    f"{resp_name}, state={state_name}, "
                    f"bytes_received={status['bytes_received']}"
                )
                if status["bytes_received"] != file_size:
                    print(
                        "Warning: bootloader reported bytes_received="
                        f"{status['bytes_received']}, expected {file_size}."
                    )
            elif final_payload:
                print(
                    "Upload process finished. Final bootloader state: "
                    f"{resp_name}, payload={list(final_payload)}"
                )
            else:
                print(f"Upload process finished. Final bootloader state: {resp_name}")


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
