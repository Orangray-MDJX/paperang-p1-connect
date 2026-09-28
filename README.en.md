# Paperang P1 Connect

Unofficial Windows service for the Paperang P1 thermal printer: USB and
classic-Bluetooth printing, a durable SQLite job queue, a LAN IPP server
(discoverable by Android/iOS system printing and Windows), an HTTP API, MCP
tools, plus a tray icon and a WinUI 3 management window.

> **Disclaimer**: Not affiliated with Paperang / Zuoyebang. This is an
> interoperability implementation for devices you own. No vendor binaries are
> distributed; no encryption or access control is circumvented. See
> [docs/protocol-a5.md](docs/protocol-a5.md) for the wire protocol. Provided
> as-is — use at your own risk and in accordance with local law.

## Highlights

- **A5 protocol** (P1 new firmware, verified on 01.03.18) with byte-exact
  capture-vector tests; legacy gen1/gen2 protocols included for older models.
- **Transports**: USB (system usbprint.sys, no Zadig), RFCOMM, experimental
  BLE, optional vendor-library bridge.
- **Durable job queue**: survives restarts; out-of-paper pauses as `held`,
  interrupted sends become `unknown` and are never auto-reprinted.
- **LAN IPP printing**: PWG Raster / Apple Raster (URF) / JPEG / PDF with
  Bonjour discovery and subnet access control.
- **Long-image printing**: phone-browser upload with B/W preview, up to ~2 m.
- **HTTP API** on 127.0.0.1:8765 and **MCP** tools for AI clients.

## Compatibility

| Model / firmware | USB | Bluetooth | BLE |
|---|---|---|---|
| P1 · A5 01.03.18 | verified | verified (RFCOMM) | experimental |
| Other A5 firmwares | unverified | unverified | — |
| Legacy gen1/gen2 | supported | supported | supported |

See [docs/VERIFICATION.md](docs/VERIFICATION.md) for the full verified
capability matrix.

## Install (Windows 10/11)

```powershell
git clone <repo-url>
cd paperang-p1-connect
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
```

PDF/PS rendering is optional: install Ghostscript, or set `gs_path`.

## Quick start

```powershell
.venv\Scripts\python.exe scripts\run_service.py   # background service
start http://127.0.0.1:8765/                      # web console
.venv\Scripts\python.exe -m paperang_p1 print-text "hello"
```

Tray: `.venv\Scripts\python.exe -m paperang_p1.tray`. LAN printing setup:
`installer/enable_lan.ps1` + [docs/LAN-PRINTING.md](docs/LAN-PRINTING.md).

## Testing

```powershell
.venv\Scripts\python.exe -m pytest -q   # no physical device required
```

## License

[MIT](LICENSE); third-party notices in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
The Chinese [README.md](README.md) is the primary documentation.
