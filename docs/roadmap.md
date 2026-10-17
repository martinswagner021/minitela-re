# Roadmap / not implemented yet

This project currently does everything that a stock panel supports at runtime:
values, pages, notifications, clock, brightness and GIF *selection*. The
remaining work is about **writing flash** — custom GIFs and custom interfaces.

---

## 1. Flash backup (do this first)

Before any flash write, add a safe **dump** of the device regions using the
`UPLOAD_DATA 0x0083` path. This gives a restore point so experiments are
recoverable. Until this exists, do not write flash.

```
UPLOAD_DATA 0x0083  -> read regions listed in docs/hardware-and-flash.md
```

## 2. Flash write path

Implement the download sequence and expose it in the daemon/CLI:

```
HANDSHAKE 0x0080
REQUEST_DOWNLOAD 0x0081 (addr, length, md5)
DOWNLOAD_DATA 0x0082   × N
DOWNLOAD_COMPLETE 0x008F
SWITCH_STATE / REBOOT
```

Prove it by re-uploading a region's **own** contents (a no-op restore) before
writing anything new. Target regions: `texture` (`0x08100000`) and
`texture_gif` (`0x08500000`).

## 3. Custom GIF

The device wants a compiled `GIF_0.acf`. Two routes:

* Run the vendor GIF generator under Wine to produce the ACF, then flash it; or
* reverse the ACF container from input/output examples and reimplement it.

## 4. Custom UI / layout

Same boundary: author a project bundle (`data.json` + assets), compile to
`Texture.acf`, flash it. Blocked on the ACF container / the vendor compiler;
see [`hardware-and-flash.md`](hardware-and-flash.md).

## 5. Host-side niceties (optional)

* CPU/GPU/WiFi-signal readouts are impossible on this firmware (the registers
  do not exist). No work here — document only.
* The web UI could gain authentication if it is ever exposed beyond localhost.
* Package as a distro/Flatpak so users don't copy files by hand.

---

## Status summary

| Item | State |
|---|---|
| Register writes, pages, notifications, clock, brightness | done |
| Preloaded GIF selection | done |
| Flash backup (`UPLOAD_DATA`) | todo |
| Flash write path | todo |
| Custom GIF upload | todo |
| Custom UI / ACF generation | todo |
