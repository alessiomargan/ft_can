# CAN Loader Flow-Control Trial Report

## Summary

Flow-control tuning was evaluated on the FT bootloader host using the VA416xx firmware image `ft_vor.bin` (21128 bytes) over CAN at 250000 bps.

The tested results show that `WINDOW_SIZE=16` and `ACK_INTERVAL=16` is the best stable operating point observed in this hardware and protocol configuration. Larger windows can still complete, but they no longer improve throughput and instead expose protocol turnaround limits on the target side.

## Test Conditions

- Host tool: `can_loader.py`
- Image: `ft_vor.bin`
- File size: 21128 bytes
- CAN bitrate: 250000 bps
- Slot: 0
- Interface: `socketcan` on `can0`

## Trial Results

| Window | Ack Interval | Ack Timeout | Result | Time | Avg Rate | Notes |
| --- | --- | --- | --- | ---: | ---: | --- |
| 4 | 4 | 0.01 | Pass | 7.924 s | 2666.3 B/s | Stable, no recovery events |
| 6 | 6 | 0.01 | Pass | 5.368 s | 3935.7 B/s | Stable, no recovery events |
| 8 | 8 | 0.01 | Pass | 4.098 s | 5156.3 B/s | Stable, no recovery events |
| 10 | 10 | 0.01 | Pass | 3.323 s | 6357.6 B/s | Stable, no recovery events |
| 16 | 16 | 0.01 | Pass | 2.180 s | 9693.3 B/s | Best tested result |
| 20 | 20 | 0.01 | Pass | 4.738 s | 4458.9 B/s | Stable only with grace waits; slower than 16 |
| 8 | 4 | 0.02 | Fail | n/a | n/a | Tail-end retransmit loop |
| 4 | 8 | 0.01 | Invalid | n/a | n/a | Rejected by host validation: ack interval > window |

## Observations

1. Throughput improved monotonically from `4/4` through `16/16`.
2. The `16/16` configuration delivered the best measured throughput while remaining fully stable.
3. The `20/20` configuration completed without retransmission fallback after host-side fixes, but required a grace wait on essentially every window. That indicates the bootloader target needs more than `0.01 s` to respond at that burst size.
4. Because `20/20` completed much slower than `16/16`, the limiting factor is no longer host logic. It is the target's processing and protocol turnaround budget.
5. Mixed settings where `ACK_INTERVAL < WINDOW_SIZE` were not robust in this environment and should not be used as defaults.

## Conclusion

`WINDOW_SIZE=16` and `ACK_INTERVAL=16` should be treated as the current hardware and protocol limit for this deployment.

This conclusion is based on two facts:

1. `16/16` is the fastest stable configuration observed.
2. Increasing the burst size to `20/20` did not improve throughput and instead exposed a target-side response limit that forced the host to wait for delayed acknowledgements.

In practical terms, the host can send larger windows, but the receiver does not acknowledge them quickly enough for those larger settings to be beneficial. That makes `16` the effective performance ceiling for the present bootloader implementation and CAN link settings.

## Recommended Defaults

- `WINDOW_SIZE=16`
- `ACK_INTERVAL=16`
- `ACK_TIMEOUT=0.01`

## Follow-Up

If higher throughput is required beyond the `16/16` profile, the next changes need to be on the target bootloader side rather than in the host:

- reduce target-side ACK latency
- reduce per-window processing overhead
- revisit the flow-control protocol for large bursts
