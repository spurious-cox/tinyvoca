# TinyVoca

A Mac app for trying out **[tiny-voca](https://github.com/n4ze3m/tiny-voca)**, a very small text-to-speech model that runs on your own computer, and for comparing it with the voices built into macOS.

Type or paste text of any length, pick one or several voices, and listen. Everything runs locally: no account, no cloud service, and your text never leaves the Mac.

## About tiny-voca

tiny-voca is the work of Muhammed Nazeem ([n4ze3m](https://github.com/n4ze3m)): a 4.5-million-parameter English model with two American voices (F2, female, and M2, male) that is fast enough to run on a laptop CPU. TinyVoca is only a front end for it. The model, its code and its documentation live here:

- **Code and documentation:** <https://github.com/n4ze3m/tiny-voca>
- **Model weights (Hugging Face):** <https://huggingface.co/n4ze3m/tiny-voca>
- **Dataset:** <https://huggingface.co/datasets/n4ze3m/tiny-voca>
- **Web demo (runs in your browser):** <https://tiny-voca.n4ze3m.com>
- **Phonemizer it uses (dizione):** <https://github.com/n4ze3m/dizione>

## What TinyVoca does

- **Two kinds of voices in one list:** F2 and M2 from tiny-voca, plus the English voices already on your Mac (Alex, Ava, Samantha and so on).
- **Speak** makes the whole audio and plays it.
- **Speak live** speaks in short pieces, so moving a slider, or changing the voice or the seed, while it speaks changes what you hear within a second or two. This is the way to test voices actively.
- **Compare** speaks the same text in every voice you selected, in the order you selected them. With "Say "I am <voice>" first" checked, each voice introduces itself before it speaks, so you always know whose turn it is.
- **Save WAV…** saves the text, spoken by the first voice you selected, as a WAV audio file. **Open text file…** loads a plain text file (up to 1 MB) into the text box.
- **Controls:** Speed (all voices), and Pitch shift, Pitch range and Seed (tiny-voca voices only; system voices ignore them). Hover over any control for an explanation.
- **Remembers everything:** your text, the voices you chose, the sliders and the voice sets come back the next time you open the app.

### What is and isn't from tiny-voca

TinyVoca covers tiny-voca's speaking side: both voices, speed, pitch shift, pitch range, seed, long text read sentence by sentence, text from a file, and WAV output (the same things its `infer` command does). It does not include tiny-voca's ONNX export, its training and evaluation tools, or its browser demo; see the [tiny-voca repository](https://github.com/n4ze3m/tiny-voca) for those.

### Choosing voices

- Click a voice to select it. **⌘-click** adds a voice to the selection or removes it. The numbers show the order Compare will use. Speak and Speak live use the first voice you selected.
- **⌥-click (Option)** grays a voice out so it can't be used, or brings it back.
- **Voice sets…** loads categories of system voices into the list, with check marks: English (US), UK, Australia, Ireland, India and South Africa, plus novelty voices, classic robotic voices and character voices. Changes show in the list at once.

## Requirements

- A Mac with **Apple silicon** (M1 or newer) running **macOS 12 or later**. PyTorch, which tiny-voca needs, no longer provides Intel Mac builds.
- **Python 3.10 or newer.** Most people already have it; if not, `brew install python` or the installer from [python.org](https://www.python.org/downloads/macos/) will do. TinyVoca looks in the usual places and tells you if it can't find one.
- An internet connection **on the first launch only**, and about 1 GB of free disk space.

## Install

**Download:** get `TinyVoca-<version>.dmg` from the [Releases page](https://github.com/spurious-cox/tinyvoca/releases), open it, and drag TinyVoca to Applications. The app is signed and notarized by Apple, so it opens without warnings.

**Homebrew:**

```bash
brew install --cask spurious-cox/tap/tinyvoca
```

### First launch

The first time you open TinyVoca it sets itself up, which takes a few minutes and shows its progress: it creates a Python environment, installs PyTorch and tiny-voca (about 250 MB), and downloads the model weights (about 25 MB) from Hugging Face. After that, it starts in a few seconds and works offline.

Everything it installs lives in one folder, `~/Library/Application Support/TinyVoca`. The versions of tiny-voca and dizione it installs are pinned to the commits this release was tested with.

## Uninstall

Drag TinyVoca to the Trash (or `brew uninstall --cask tinyvoca`), and delete `~/Library/Application Support/TinyVoca` to reclaim the 1 GB.

## Troubleshooting

- **"TinyVoca needs Python 3.10 or newer":** install Python (see above), then press ⌘R.
- **"The setup did not finish":** usually the connection dropped. Press ⌘R to try again; it picks up where it stopped.
- **A system voice stops partway through:** macOS treats text in angle brackets such as `<this>` as markup and stops there. TinyVoca removes the brackets for system voices, but other markup-like text can still confuse them.
- **System voices sound odd:** the list shows the voices installed on your Mac. Add more, including higher-quality ones, in System Settings → Accessibility → Spoken Content → System Voice → Manage Voices.
- **Menu:** View → Reload (⌘R) restarts the speech server. The Help menu links to the tiny-voca pages.

## Building from source

```bash
git clone https://github.com/spurious-cox/tinyvoca.git
cd tinyvoca
./build.sh --install     # builds, signs and installs /Applications/TinyVoca.app
```

`build.sh` needs the Xcode command line tools and a code-signing identity (edit `SIGN_ID`, or use `-` for an ad hoc signature). To run just the web interface without the app, run `./setup-engine.sh ./engine` once, then `cd engine && venv/bin/python ../gui.py`, and open <http://127.0.0.1:8765>.

## Credits and licenses

- **TinyVoca** (this app): MIT license, © 2026 Tim McCoy. See [LICENSE](LICENSE).
- **tiny-voca** (model, weights and code) and **dizione**: © Muhammed Nazeem, Apache-2.0. TinyVoca doesn't include them; it downloads them on first launch from the sources linked above. Please read their pages for the model's limits and its dataset's license (CC BY 4.0).
- **System voices** belong to Apple and are used through the macOS `say` command.
