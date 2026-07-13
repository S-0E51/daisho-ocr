# 代書 Daisho — Japanese OCR capture for Windows

Capture any region of your screen, read the Japanese in it, and send the text
straight to a reader that explains the grammar — without leaving the page you
are on.

Daisho is a PyQt6 desktop app. You drag a transparent overlay over some text
(a manga panel, a game, a PDF, a video), press a hotkey, and it OCRs the region
and pushes the result into a bundled reader that segments the sentence, glosses
every word, names each verb form, and explains what each particle is doing.

- **Screen capture** — draggable, resizable overlay; global hotkeys, including
  extra mouse buttons.
- **Five OCR engines** — PaddleOCR PP-OCRv5 (default), PaddleOCR-VL, manga-ocr
  for stylized manga/game text, Surya, and RapidOCR. Switchable at runtime.
- **A reader that teaches** — grammar derived from the parser's own morphology,
  contextual particle explanations, per-word definitions, Anki export.
- **Runs offline** — optionally, end to end. See *Privacy* below.

---

## ⚠️ Privacy, before you start

Out of the box, the reader parses sentences with **[ichi.moe](https://ichi.moe)**,
an online service. **Your captured text is sent there.**

Install the optional offline parser (**[step 4](#4-optional-offline-parsing-recommended)**)
and everything stays on your machine — no network, no third party. The app
switches to it automatically once it is present; you do not need to change a
setting.

If you are capturing anything you would not paste into a public website, do
step 4 first.

---

## Requirements

| | |
|---|---|
| **Windows** | 10 or 11 |
| **Python** | 3.10 or newer — [python.org](https://www.python.org/downloads/) (tick *"Add Python to PATH"*) |
| **Node.js** | 21 or newer — [nodejs.org](https://nodejs.org/) (builds the reader) |
| **Git** | [git-scm.com](https://git-scm.com/) |
| **GPU** | Optional. NVIDIA + CUDA makes OCR much faster. |

## Install

```bat
git clone --recurse-submodules https://github.com/shanlichin2021/daisho-ocr.git
cd daisho-ocr
setup.bat
```

`--recurse-submodules` matters — the reader lives in a submodule. If you forget
it, run `git submodule update --init --recursive`.

`setup.bat` creates a virtualenv, installs the Python dependencies, and builds
the reader. It downloads a few GB of PyTorch/Paddle wheels, so give it ten
minutes and a decent connection. For an NVIDIA GPU build, run `setup_gpu.bat`
instead.

## Run

```bat
start.bat
```

The first capture is slow: OCR model weights are downloaded on first use, then
cached. Subsequent captures are fast.

**Default hotkeys** — drag the overlay over some text, then:

| | |
|---|---|
| `Ctrl` + `Q` | capture and OCR the overlay region |
| ` (backtick) | move the overlay to the mouse |
| `Ctrl`+`Shift`+`S` | scan mode |

All of them are rebindable in Settings.

## 4. Optional: offline parsing (recommended)

This removes the dependency on ichi.moe entirely. It installs
[Ichiran](https://github.com/tshatrov/ichiran) — a Japanese morphological
analyser — inside WSL.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_ichiran_wsl.ps1
```

It is a **long** install (roughly an hour, mostly unattended): WSL2 + Ubuntu,
PostgreSQL, SBCL, and a ~200 MB dictionary database. The script is idempotent —
if it fails partway, run it again.

When it finishes, the reader picks it up automatically. Nothing you capture
leaves the machine after that.

## Optional: local AI analysis

The reader can add sentence-level explanations using a **local**
[Ollama](https://ollama.com/) server. There is no cloud provider and no API key
— if you do not run Ollama, this simply stays off, and the grammar engine still
works, because it is rule-based rather than model-based.

---

## Troubleshooting

**`setup.bat` fails on PaddlePaddle.** Paddle is pinned to `3.2.0` on purpose —
3.3.0 has an oneDNN bug that breaks PP-OCRv5. Let the script manage it; do not
upgrade Paddle by hand.

**The reader never opens.** It has to be built: `build_japreader.bat` (needs
Node on PATH). Check `study\japReader\out\japreader-win32-x64\japreader.exe`
exists.

**"Ichiran command was not found."** Expected until you do step 4. The app falls
back to ichi.moe, and the reader still works.

**A capture returns nothing.** Try a different OCR engine in Settings — manga-ocr
is far better on stylized/vertical text, PaddleOCR on clean horizontal text.

**Logs** are in `logs\`. They record the text you capture, so do not paste them
into a bug report without reading them first.

---

## Licence and credits

**GPL-3.0.** See [LICENSE](LICENSE).

The reader is a fork of **[japReader](https://github.com/marisukukise/japReader)**
by marisukukise (originally by [seth-js](https://github.com/seth-js/japReader)),
GPL-3.0. Our changes are listed in the submodule's `CHANGES.md`.

Word definitions come from **JMdict** (Electronic Dictionary Research and
Development Group, CC BY-SA). Segmentation and morphology come from
**[Ichiran](https://github.com/tshatrov/ichiran)**. Full attribution, including
the grammar packs, is in [NOTICE.md](NOTICE.md).
