"""Local web GUI for tiny-voca and the macOS system voices.  Run: python gui.py  (then open http://127.0.0.1:8765)

Standard library only besides tiny-voca itself. Serves on localhost only. TinyVoca.app runs this for you.

tiny-voca is by Muhammed Nazeem (n4ze3m), Apache-2.0: https://github.com/n4ze3m/tiny-voca
"""
import base64
import io
import re
import subprocess
import tempfile
import json
import os
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("DIZIONE_DATA", str(HERE / "weights" / "phonemizer"))
CHECKPOINT = HERE / "weights" / "tiny-voca.pt"
SETTINGS = HERE / "settings.json"
PORT = int(os.environ.get("PORT", "8765"))

from tiny_voca.infer import _CLAUSE_END, ENGLISH_ONLY, FRONTEND_VARIABLE, finished, limit_peak, load_model, match_frontend, sentences, speak_text  # noqa: E402
from tiny_voca.text import NothingToPronounce  # noqa: E402

if FRONTEND_VARIABLE not in os.environ:
    match_frontend(CHECKPOINT)
MODEL = load_model(CHECKPOINT)
RATE = MODEL.config.sample_rate
LOCK = threading.Lock()  # one synthesis at a time


def to_wav(wave_tensor):
    pcm = (wave_tensor.clamp(-1, 1) * 32767).short().numpy().tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


TINY = ("F2", "M2")


# Apple's novelty voices (sound effects, jokes, instruments), the old robotic ones, and a few character voices.
NOVELTY = {"Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Deranged", "Good News", "Hysterical",
           "Jester", "Organ", "Pipe Organ", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox"}
CLASSIC = {"Fred", "Junior", "Kathy", "Ralph"}
CHARACTER = {"Grandma", "Grandpa", "Flo", "Sandy", "Shelley"}
LANGS = {"ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali", "ca": "Catalan", "kk": "Kazakh", "kn": "Kannada", "lt": "Lithuanian",
         "sl": "Slovenian", "ta": "Tamil", "te": "Telugu", "cs": "Czech", "da": "Danish", "de": "German", "el": "Greek",
         "es": "Spanish", "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi", "hr": "Croatian", "hu": "Hungarian",
         "id": "Indonesian", "it": "Italian", "ja": "Japanese", "ko": "Korean", "ms": "Malay", "nb": "Norwegian",
         "nl": "Dutch", "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sk": "Slovak",
         "sv": "Swedish", "th": "Thai", "tr": "Turkish", "uk": "Ukrainian", "vi": "Vietnamese", "zh": "Chinese"}
EN_REGIONS = {"en_US": "English (US)", "en_GB": "English (UK)", "en_AU": "English (Australia)", "en_IE": "English (Ireland)",
              "en_IN": "English (India)", "en_ZA": "English (South Africa)"}


def categorize(name, loc):
    base = re.sub(r"\s*\(.*\)$", "", name)
    lang = loc.split("_")[0]
    if lang == "en":   # these names also exist in other languages (Eddy, Flo, ...), which stay with their language
        if base in NOVELTY:
            return "novelty"
        if base in CLASSIC:
            return "classic"
        if base in CHARACTER:
            return "character"
    if lang == "en":
        return loc if loc in EN_REGIONS else "en_other"
    return "lang_" + lang


def system_voices():
    """All macOS voices from `say -v ?` as [(name, category)]."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found, seen = [], set()
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2,3}_[A-Z0-9]{2,3})\s+#", line)
        if m and m.group(2).startswith("en_") and m.group(1).strip() not in seen:   # English voices only
            name = m.group(1).strip()
            seen.add(name)
            found.append((name, categorize(name, m.group(2))))
    return sorted(found, key=lambda x: x[0].lower())


VOICES = system_voices()
SYSTEM = {name for name, _ in VOICES}


def category_list():
    counts = {}
    for _, c in VOICES:
        counts[c] = counts.get(c, 0) + 1
    cats = []
    for key, label in list(EN_REGIONS.items()) + [("en_other", "English (other)")]:
        cats.append((key, label, "English", counts.get(key, 0)))
    cats += [("novelty", "Novelty voices", "Special", counts.get("novelty", 0)),
             ("classic", "Classic robotic voices", "Special", counts.get("classic", 0)),
             ("character", "Character voices", "Special", counts.get("character", 0))]
    for key in sorted(k for k in counts if k.startswith("lang_")):
        code = key[5:]
        cats.append((key, LANGS.get(code, code), "Other languages", counts[key]))
    notes = {"novelty": "Sound-effect, joke and instrument voices: " + ", ".join(sorted(NOVELTY)),
             "classic": "Old robotic-sounding voices: " + ", ".join(sorted(CLASSIC)),
             "character": "Character voices: " + ", ".join(sorted(CHARACTER)) + " (English)"}
    return [{"key": k, "label": l, "group": g, "count": n, "note": notes.get(k, "")} for k, l, g, n in cats if n]


def synth_system(text, voice, speed):
    if voice not in SYSTEM:
        return {"error": f"Unknown voice: {voice}"}
    # `say` treats <...> as markup and silently stops speaking there, and [[...]] as embedded commands.
    text = re.sub(r"[<>]", "", text).replace("[[", "[ [").replace("]]", "] ]")
    wpm = max(50, min(500, round(175 * speed)))
    start = time.time()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.wav")
        try:
            r = subprocess.run(
                ["say", "-v", voice, "-r", str(wpm), "-o", path, "--file-format=WAVE", "--data-format=LEI16@24000", "-f", "-"],
                input=text.encode("utf-8"), capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        if r.returncode != 0 or not os.path.exists(path):
            return {"error": f"say failed for {voice}: {r.stderr.decode(errors='replace').strip()[:200]}"}
        data = Path(path).read_bytes()
    try:
        with wave.open(io.BytesIO(data)) as w:
            seconds = w.getnframes() / w.getframerate()
    except wave.Error:
        return {"error": f"{voice} produced no audio."}
    took = time.time() - start
    return {"wav": base64.b64encode(data).decode(), "seconds": round(seconds, 2), "took": round(took, 2),
            "realtime": round(seconds / took, 1) if took else None, "peak": None, "scaled": False,
            "utterances": 1, "phonemes": []}


def synth(req):
    text = str(req.get("text", "")).strip()
    if not text:
        return {"error": "Type some text first."}
    voice = req.get("voice", "F2")
    if voice not in TINY:
        return synth_system(text, voice, float(req.get("speed", 1)))
    start = time.time()
    try:
        with LOCK:
            raw, spoken = speak_text(
                MODEL, text, voice,
                speed=float(req.get("speed", 1)),
                pitch_shift=float(req.get("pitch_shift", 0)),
                seed=int(req.get("seed", 0)),
                pitch_range=float(req.get("pitch_range", 1)),
                peak=None,
            )
    except NothingToPronounce:
        return {"error": f"{ENGLISH_ONLY}. Nothing in the text could be read."}
    except Exception as exc:  # shown in the GUI
        return {"error": f"{type(exc).__name__}: {exc}"}
    took = time.time() - start
    loudest = float(raw.abs().max())
    out = limit_peak(raw)
    seconds = len(out) / RATE
    return {
        "wav": base64.b64encode(to_wav(out)).decode(),
        "seconds": round(seconds, 2),
        "took": round(took, 2),
        "realtime": round(seconds / took, 1) if took else None,
        "peak": round(loudest, 4),
        "scaled": out is not raw,
        "utterances": len(spoken),
        "phonemes": [" ".join(p.symbols) for p in spoken],
    }


def chunks(text, fine=False):
    """Sentences; with fine=True also cut after commas, colons and dashes into pieces of at least 4 words,
    so a setting changed during speech takes effect within a second or two."""
    if not text:
        return []
    out = []
    for s in sentences(finished(text)):
        if not fine:
            out.append(s)
            continue
        local, buf = [], ""
        for part in _CLAUSE_END.split(s):
            buf = (buf + " " + part).strip()
            if len(buf.split()) >= 4:
                local.append(buf)
                buf = ""
        if buf:
            if local:
                local[-1] += " " + buf
            else:
                local.append(buf)
        out.extend(local)
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/voices":
            self._send(200, json.dumps({"tiny": list(TINY), "voices": [{"id": n, "cat": c} for n, c in VOICES], "cats": category_list()}))
        elif self.path == "/settings":
            try:
                self._send(200, SETTINGS.read_text(encoding="utf-8"))
            except OSError:
                self._send(200, "{}")
        elif self.path == "/info":
            self._send(200, json.dumps({"rate": RATE, "params": sum(p.numel() for p in MODEL.parameters())}))
        else:
            self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 2_000_000:
            return self._send(413, json.dumps({"error": "Too large."}))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, json.dumps({"error": "Bad JSON."}))
        if self.path == "/speak":
            self._send(200, json.dumps(synth(req)))
        elif self.path == "/sentences":
            self._send(200, json.dumps(chunks(str(req.get("text", "")).strip(), bool(req.get("fine")))))
        elif self.path == "/settings":
            keep = {k: req[k] for k in ("voices", "cats", "off", "intro", "text", "speed", "pitch", "range", "seed") if k in req}
            SETTINGS.write_text(json.dumps(keep), encoding="utf-8")
            self._send(200, "{}")
        else:
            self._send(404, "{}")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>tiny-voca Tester</title>
<style>
:root{--bg:#f6f7f9;--fg:#1c1e21;--card:#fff;--line:#d9dde3;--acc:#2563eb;--mut:#667085;--ok:#15803d;--bad:#b42318}
@media(prefers-color-scheme:dark){:root{--bg:#15171a;--fg:#e8eaed;--card:#1f2226;--line:#33373d;--acc:#6ea0ff;--mut:#9aa3af;--ok:#4ade80;--bad:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:baseline}
h1{font-size:18px;margin:0}small,.mut{color:var(--mut)}a{color:var(--acc)}
main{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;padding:16px 20px;max-width:900px;margin:auto}
@media(max-width:850px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:16px}
h2{font-size:14px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
textarea{width:100%;min-height:170px;resize:vertical;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);font:inherit}
.row{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin:10px 0}
label{display:flex;flex-direction:column;gap:2px;font-size:13px;color:var(--mut)}
label b{color:var(--fg);font-weight:600}
input[type=range]{width:170px}input[type=number]{width:80px;padding:4px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px}
select{padding:5px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px}
button{padding:7px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;cursor:pointer}
button.p,button.on{background:var(--acc);border-color:var(--acc);color:#fff}button:disabled{opacity:.5;cursor:default}button.on:disabled{opacity:1}
button.s{padding:3px 9px;font-size:13px}
.vwrap{display:flex;flex-direction:column;gap:2px;font-size:13px;color:var(--mut)}
.vpair{display:flex;gap:10px;align-items:stretch;max-width:100%}
.vlist{width:max-content;min-width:200px;max-width:100%;height:190px;overflow:auto;border:1px solid var(--line);border-radius:6px;background:var(--bg);padding:2px;user-select:none;-webkit-user-select:none}
.vrow{padding:2px 8px;border-radius:4px;cursor:default;white-space:nowrap;color:var(--fg);display:flex;justify-content:space-between;gap:10px}
.vrow.sel{background:var(--acc);color:#fff}.vrow.off{color:var(--mut);opacity:.4;font-style:italic}
.vhead{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center}
.vrow .n{font-weight:600}
#setpanel{width:max-content;min-width:200px;max-width:100%;height:190px;overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 10px}
#setpanel[hidden]{display:none}
#setpanel h3{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);margin:10px 0 4px}#setpanel h3:first-child{margin-top:0}
.ck{flex-direction:row;align-items:center;gap:6px;color:var(--fg);font-size:13px;padding:1px 0}
#status{min-height:22px}.err{color:var(--bad)}.ok{color:var(--ok)}
.ph{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--mut);margin:2px 0;word-break:break-word}
ul{list-style:none;margin:0;padding:0}li{display:flex;gap:6px;align-items:center;padding:6px 0;border-top:1px solid var(--line)}
li:first-child{border-top:0}li span.t{flex:1;min-width:0;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
li.now{background:color-mix(in srgb,var(--acc) 15%,transparent)}
.h{display:grid;grid-template-columns:1fr auto;gap:4px 10px;padding:8px 0;border-top:1px solid var(--line);font-size:13px}
.h:first-child{border-top:0}audio{width:100%;height:34px}
</style></head><body>
<header><h1>tiny-voca Tester</h1><small id="info">loading model…</small><small style="margin-left:auto">tiny-voca by n4ze3m: <a href="https://github.com/n4ze3m/tiny-voca" target="_blank">GitHub</a> · <a href="https://huggingface.co/n4ze3m/tiny-voca" target="_blank">model</a> · <a href="https://huggingface.co/datasets/n4ze3m/tiny-voca" target="_blank">dataset</a> · <a href="https://tiny-voca.n4ze3m.com" target="_blank">demo</a></small></header>
<main>
<div>
 <div class="card"><h2>Text</h2>
  <textarea id="text" placeholder="Type or paste text of any length. It is read sentence by sentence."></textarea>
  <div class="row">
   <div class="vwrap"><div class="vhead">Voices <small>(&#8984;-click: add or remove, &#8997;-click: gray out or restore)</small> <button class="s" id="sets" title="Choose which categories of system voices are loaded into the list: English regions, novelty, classic and character voices, and other languages.">Voice sets…</button> <label class="ck" title="Before the text, each voice says its own name: &quot;I am Ava&quot;. It applies to Speak, Speak live (once, at the start) and Compare."><input type="checkbox" id="intro" checked> Say &ldquo;I am &lt;voice&gt;&rdquo; first</label></div>
    <div class="vpair"><div id="voice" class="vlist" title="Click selects one voice. &#8984;-click adds a voice to the selection or removes it. &#8997;-click (Option) grays a voice out so it cannot be used, or restores it. Speak and Speak live use the first voice selected; Compare speaks every selected voice in turn, in the order selected (the numbers show the order). F2 and M2 are tiny-voca; the rest are macOS system voices. Change the selection during Speak live to hear another voice at once."></div>
    <div id="setpanel" hidden></div></div></div>
  </div>
  <div class="row">
   <label title="Speaking rate. 1.00 is normal; higher is faster (up to 2x), lower is slower (down to half speed). Pitch stays about the same. It applies to all voices (system voices use it as words per minute). Move it during Speak live to hear the change as it speaks."><span>Speed <b id="vs">1.00</b></span><input type="range" id="speed" min="0.5" max="2" step="0.05" value="1"></label>
   <label title="Raises or lowers the whole voice. 0 is as the model predicts; positive is higher, negative is lower. About 0.058 is one semitone, so 0.5 is roughly 8-9 semitones. Move it during Speak live to hear the change as it speaks. Only tiny-voca voices (F2, M2) use it."><span>Pitch shift <b id="vp">0.000</b> <small>(0.058 ≈ 1 semitone)</small></span><input type="range" id="pitch" min="-0.5" max="0.5" step="0.01" value="0"></label>
   <label title="How much the pitch moves up and down around its average. 1.00 is as predicted; 0 is flat and monotone, above 1 is more expressive or sing-song. Move it during Speak live to hear the change as it speaks. Only tiny-voca voices (F2, M2) use it."><span>Pitch range <b id="vr">1.00</b></span><input type="range" id="range" min="0" max="2" step="0.05" value="1"></label>
   <label title="Random starting value for the small natural variations in the voice. The same text and seed always sound identical; change the seed for a slightly different take. Change it during Speak live to hear a new take at once. Only tiny-voca voices (F2, M2) use it.">Seed<input type="number" id="seed" value="0"></label>
   <button class="s" id="reset">Reset</button>
  </div>
  <div class="row">
   <button id="go" title="Makes all the audio first, then plays it. Settings changed while it plays are not heard; use Speak live to test voices actively.">Speak</button>
   <button id="live" title="The way to test voices actively: speaks the text in short pieces, and moving any slider (or changing the voice or seed) while it speaks re-speaks the current piece at once with the new setting.">Speak live</button>
   <button id="both" title="Speaks the text in every selected voice in turn, in the order selected. Select two or more voices first (&#8984;-click adds a voice). If &quot;Say I am&hellip; first&quot; is checked, each voice introduces itself before it speaks.">Compare</button>
   <button id="stop" title="Stops speaking right away.">Stop</button>
   <button id="save" title="Saves the text, spoken by the first voice you selected with the current settings, as a WAV audio file. (The spoken &quot;I am&hellip;&quot; introduction is not included.)">Save WAV&hellip;</button>
   <button id="open" title="Loads the text of a plain text file (.txt, .md and the like, up to 1 MB) into the text box, replacing what is there.">Open text file&hellip;</button>
   <input type="file" id="file" accept=".txt,.md,.markdown,.text,.rtf,text/*" hidden>
   <span id="count" class="mut"></span>
  </div>
  <div id="status" class="mut"></div>
  <div id="phon"></div>
 </div>
</div>
</main>
<script>
const $=id=>document.getElementById(id);
let stopFlag=false,player=null,busy=false;
const ctl={speed:['vs',2],pitch:['vp',3],range:['vr',2]};
for(const k in ctl)$(k).oninput=()=>$(ctl[k][0]).textContent=(+$(k).value).toFixed(ctl[k][1]);
$('reset').onclick=()=>{$('speed').value=1;$('pitch').value=0;$('range').value=1;$('seed').value=0;for(const k in ctl)$(k).oninput()};
const upd=()=>{const t=$('text').value.trim();$('count').textContent=t?t.length+' characters, '+t.split(/\s+/).length+' words':''};
$('text').oninput=upd;
function req(text,voice){return {text,voice,speed:+$('speed').value,pitch_shift:+$('pitch').value,pitch_range:+$('range').value,seed:+$('seed').value}}
async function synth(text,voice){
  saveSettings();   // the voice and settings last used become the defaults next time
  const r=await fetch('/speak',{method:'POST',body:JSON.stringify(req(text,voice))});return r.json();
}
function setBusy(b,msg){busy=b;for(const id of ['go','live','both','save','open'])$(id).disabled=b;if(!b)for(const id of ['go','live','both'])$(id).classList.remove('on');if(msg!==undefined)status(msg)}
function mark(id){$(id).classList.add('on')}
function flash(id){mark(id);setTimeout(()=>$(id).classList.remove('on'),700)}
function status(m,c){$('status').textContent=m;$('status').className=c||'mut'}
function play(d){return new Promise(res=>{player=new Audio('data:audio/wav;base64,'+d.wav);player.onended=res;player.onerror=res;player.play().catch(res)})}
function spokenName(v){
  if(v==='F2')return 'F two';
  if(v==='M2')return 'M two';
  const m=v.match(/^(.*?)\s*\((Enhanced|Premium)\)/);
  return m?m[1]+' '+m[2]:v.replace(/\s*\(.*\)$/,'').trim();
}
async function run(text,voices,autoplay=true){
  for(const v of voices){
    if(stopFlag)return false;
    if($('intro').checked&&autoplay){   // the voice introduces itself first
      status('Introducing '+v+'…');
      const n=await synth('I am '+spokenName(v)+'.',v);
      if(n.error){status(n.error,'err');return false}
      await play(n);
      if(stopFlag)return false;
    }
    status('Making '+v+'… be patient on long text');
    const d=await synth(text,v);
    if(d.error){status(d.error,'err');return false}
    $('phon').innerHTML='';d.phonemes.forEach(p=>{const e=document.createElement('div');e.className='ph';e.textContent=p;$('phon').append(e)});
    status(v+': '+d.seconds+' s of speech in '+d.took+' s','ok');
    if(autoplay)await play(d);
  }
  return true;
}
$('go').onclick=async()=>{stopFlag=false;setBusy(true);mark('go');await run($('text').value,[firstVoice()]);setBusy(false)};
let liveOn=false,changed=false,liveCancel=null,debounce=null;
const settingsKey=()=>JSON.stringify(req('',firstVoice()));
function playLive(d){return new Promise(res=>{
  player=new Audio('data:audio/wav;base64,'+d.wav);
  liveCancel=()=>{player.pause();res('changed')};
  player.onended=()=>res('ended');player.onerror=()=>res('ended');
  player.play().catch(()=>res('ended'));
})}
async function liveText(text){
  stopFlag=false;liveOn=true;
  if($('intro').checked){
    status('Introducing '+firstVoice()+'…');
    const n=await synth('I am '+spokenName(firstVoice())+'.',firstVoice());
    if(!n.error)await play(n);
    if(stopFlag){liveOn=false;return false}
  }
  const ss=await (await fetch('/sentences',{method:'POST',body:JSON.stringify({text,fine:true})})).json();
  if(!ss.length)status('Type some text first.','err');
  let i=0;
  while(i<ss.length&&!stopFlag){
    status('Live: part '+(i+1)+' of '+ss.length+'. Move a slider to change the voice as it speaks.');
    const key=settingsKey();changed=false;liveCancel=null;
    const d=await synth(ss[i],firstVoice());
    if(d.error){if(/Nothing in the text/.test(d.error)){i++;continue}status(d.error,'err');break}
    if(stopFlag)break;
    if(changed||key!==settingsKey())continue;
    $('phon').innerHTML='';d.phonemes.forEach(p=>{const e=document.createElement('div');e.className='ph';e.textContent=p;$('phon').append(e)});
    if(await playLive(d)==='changed')continue;
    i++;
  }
  liveOn=false;liveCancel=null;
  const done=!stopFlag&&i>=ss.length&&ss.length>0;
  if(done)status('Finished.','ok');
  return done;
}
$('live').onclick=async()=>{setBusy(true);mark('live');await liveText($('text').value);setBusy(false)};
for(const id of ['speed','pitch','range','seed','voice'])$(id).addEventListener('input',()=>{
  if(!liveOn)return;changed=true;clearTimeout(debounce);
  debounce=setTimeout(()=>{if(liveCancel)liveCancel()},150);
});
$('both').onclick=async()=>{
  const sel=picked();
  if(sel.length<2){status('Cmd-click two or more voices in the list to compare them.','err');return}
  stopFlag=false;setBusy(true);mark('both');await run($('text').value,sel);setBusy(false)};
function b64ToBlob(b64){const bin=atob(b64),a=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);return new Blob([a],{type:'audio/wav'})}
$('save').onclick=async()=>{
  const t=$('text').value.trim();
  if(!t){status('Type some text first.','err');return}
  const v=firstVoice();
  stopFlag=false;setBusy(true);mark('save');status('Making '+v+' for the file… be patient on long text');
  const d=await synth(t,v);
  setBusy(false);
  if(d.error){status(d.error,'err');return}
  const name='tiny-voca-'+v.replace(/[^A-Za-z0-9]+/g,'-').replace(/^-|-$/g,'')+'.wav';
  const h=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.save;
  if(h){h.postMessage({name,b64:d.wav});status('Choose where to save '+name+'.','ok')}   // the app shows its Save panel
  else{const a=document.createElement('a');a.href=URL.createObjectURL(b64ToBlob(d.wav));a.download=name;document.body.append(a);a.click();a.remove();status('Saved '+name+' ('+d.seconds+' s).','ok')}
};
$('open').onclick=()=>$('file').click();
$('file').onchange=async()=>{
  const f=$('file').files[0];$('file').value='';
  if(!f)return;
  if(f.size>1048576){status(f.name+' is larger than 1 MB.','err');return}
  const txt=await f.text();
  $('text').value=txt;upd();saveSettings();status('Loaded '+f.name+'.','ok');
};
$('stop').onclick=()=>{flash('stop');stopFlag=true;if(player){player.pause();player.dispatchEvent(new Event('ended'));player.onended&&player.onended()}status('Stopped.')};
const ids=['speed','pitch','range','seed'];
let order=[];   // selected voices, in the order they were selected
let VOICES=[],CATS=[],onCats=new Set(),off=new Set();
const DEFAULT_CATS=['en_US','en_AU','en_IE','en_IN','en_ZA'];
const TINYIDS=['F2','M2'];
const TAGS={en_US:'US',en_GB:'UK',en_AU:'AU',en_IE:'IE',en_IN:'IN',en_ZA:'ZA',en_other:'',novelty:'novelty',classic:'classic',character:'character'};
const tagOf=v=>{const x=VOICES.find(y=>y.id===v);return x?TAGS[x.cat]||'':''};
const visible=()=>[...TINYIDS,...VOICES.filter(v=>onCats.has(v.cat)).map(v=>v.id)];
function picked(){return order.slice()}
const firstVoice=()=>order[0]||'F2';
function render(){
  const vis=visible();
  order=order.filter(v=>vis.includes(v)&&!off.has(v));
  if(!order.length){const f=vis.find(v=>!off.has(v));if(f)order=[f]}
  const box=$('voice');box.innerHTML='';
  vis.forEach(v=>{
    const r=document.createElement('div'),i=order.indexOf(v);
    r.className='vrow'+(off.has(v)?' off':'')+(i>=0?' sel':'');r.dataset.v=v;
    const t=document.createElement('span');t.textContent=TINYIDS.includes(v)?v+' (tiny-voca)':v;
    const g=tagOf(v);if(g){const m=document.createElement('small');m.textContent=' '+g;m.style.color='inherit';t.append(m)}
    r.append(t);
    if(i>=0){const n=document.createElement('span');n.className='n';n.textContent=i+1;r.append(n)}
    box.append(r);
  });
}
function voiceChanged(){render();for(const t of ['input','change'])$('voice').dispatchEvent(new Event(t))}
$('voice').addEventListener('mousedown',e=>{
  const r=e.target.closest('.vrow');if(!r)return;e.preventDefault();
  const v=r.dataset.v;
  if(e.altKey){off.has(v)?off.delete(v):off.add(v)}          // Option-click: gray out or restore
  else if(off.has(v)){return}
  else if(e.metaKey){if(order.includes(v)){if(order.length>1)order=order.filter(x=>x!==v)}else order.push(v)}   // Cmd-click
  else order=[v];
  voiceChanged();
});
function buildPanel(){
  const p=$('setpanel');p.innerHTML='';let group='';
  CATS.forEach(c=>{
    if(c.group!==group){group=c.group;const h=document.createElement('h3');h.textContent=group;p.append(h)}
    const l=document.createElement('label');l.className='ck';
    const cb=document.createElement('input');cb.type='checkbox';cb.checked=onCats.has(c.key);
    cb.onchange=()=>{cb.checked?onCats.add(c.key):onCats.delete(c.key);voiceChanged()};
    const t=document.createElement('span');t.textContent=c.label;if(c.note)l.title=c.note;
    const n=document.createElement('small');n.textContent='('+c.count+')';
    l.append(cb,t,n);p.append(l);
  });
}
$('sets').onclick=e=>{e.stopPropagation();$('setpanel').hidden=!$('setpanel').hidden};
document.addEventListener('mousedown',e=>{if(!$('setpanel').hidden&&!e.target.closest('#setpanel')&&e.target.id!=='sets')$('setpanel').hidden=true});
const tiny=v=>v==='F2'||v==='M2';
function syncControls(){
  const sel=picked(),a=sel.some(tiny);
  for(const id of ['pitch','range','seed']){$(id).disabled=!a;$(id).closest('label').style.opacity=a?1:.45}
  $('both').textContent=sel.length>2?'Compare '+sel.length+' voices':sel.length==2?'Compare '+sel[0]+' / '+sel[1]:'Compare';
}
$('voice').addEventListener('change',syncControls);
let saveT=null;
function saveSettings(){clearTimeout(saveT);saveT=setTimeout(doSave,150)}   // one write at a time, newest wins
function doSave(){const o={voices:picked(),intro:$('intro').checked,cats:[...onCats],off:[...off],text:$('text').value};ids.forEach(k=>o[k]=$(k).value);fetch('/settings',{method:'POST',body:JSON.stringify(o)})}
[...ids,'voice','intro'].forEach(k=>{$(k).addEventListener('change',saveSettings);$(k).addEventListener('input',saveSettings)});
$('reset').addEventListener('click',saveSettings);
let textTimer=null;$('text').addEventListener('input',()=>{clearTimeout(textTimer);textTimer=setTimeout(saveSettings,500)});
addEventListener('pagehide',doSave);
(async()=>{
  let saved={};
  try{saved=await (await fetch('/settings')).json()}catch(e){}
  try{
    const v=await (await fetch('/voices')).json();
    VOICES=v.voices;CATS=v.cats;
  }catch(e){}
  onCats=new Set(Array.isArray(saved.cats)?saved.cats:DEFAULT_CATS);
  off=new Set(Array.isArray(saved.off)?saved.off:[]);
  order=Array.isArray(saved.voices)?saved.voices:(saved.voice?[saved.voice]:['F2']);
  buildPanel();render();
  const sel=document.querySelector('.vrow.sel');if(sel)sel.scrollIntoView({block:'nearest'});
  ids.forEach(k=>{if(saved[k]!==undefined)$(k).value=saved[k]});
  if(typeof saved.intro==='boolean')$('intro').checked=saved.intro;
  if(typeof saved.text==='string'){$('text').value=saved.text;upd()}
  for(const k in ctl)$(k).oninput();
  syncControls();
})();
fetch('/info').then(r=>r.json()).then(i=>$('info').textContent=(i.params/1e6).toFixed(1)+'M parameters, '+i.rate+' Hz, runs locally');
</script></body></html>
"""

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"tiny-voca GUI on http://127.0.0.1:{PORT}  (Ctrl-C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
