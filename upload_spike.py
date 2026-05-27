"""Minimal upload page to collect the 4 real screenshots onto disk for OCR tuning.

This is a temporary spike server: its only job is to receive uploaded images and
save them into ./samples/ so we can run RapidOCR on real data and design parsing.
Run:  python upload_spike.py   then open the printed URL on the device holding the images.
"""
import os
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
os.makedirs(SAMPLES, exist_ok=True)

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>上传战绩截图</title>
<style>
  body{font-family:system-ui,sans-serif;background:#14171c;color:#e8eaed;margin:0;padding:24px;}
  h1{color:#ff7a45;font-size:20px;margin-bottom:4px;}
  p{color:#9aa1ab;font-size:14px;}
  input,button{font-size:16px;}
  #drop{border:2px dashed #3a4250;border-radius:12px;padding:32px 20px;text-align:center;margin:16px 0;transition:.15s;}
  #drop.hot{border-color:#ff7a45;background:#241b14;}
  .hint{color:#7a818b;font-size:13px;margin-top:8px;}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:center;margin-top:12px;}
  button{background:#ff7a45;color:#14171c;border:none;border-radius:8px;padding:12px 20px;cursor:pointer;}
  button.ghost{background:#2a313b;color:#e8eaed;}
  #count{color:#ff7a45;font-weight:600;}
  #thumbs{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:14px;}
  img.prev{max-width:46%;max-height:160px;border-radius:6px;border:1px solid #2a313b;}
  #out{white-space:pre-wrap;background:#1c2027;border-radius:8px;padding:12px;margin-top:16px;font-size:13px;}
</style></head>
<body>
  <h1>上传你的 4 张战绩截图</h1>
  <p>三种方式都行：① 点下方选择文件　② 把图<b>拖</b>进虚线框（含从微信聊天里拖）　③ 在微信里右键<b>复制图片</b>，然后在本页 <b>Ctrl+V 粘贴</b>。顺序随意，凑齐后点“上传”。</p>
  <div id="drop">
    <input id="files" type="file" accept="image/*" multiple>
    <div class="hint">或把图片拖到这里 / 在此页粘贴（Ctrl+V）</div>
    <div id="thumbs"></div>
    <div class="row">
      <span>已选 <span id="count">0</span> 张</span>
      <button id="send">上传</button>
      <button id="clear" class="ghost">清空</button>
    </div>
  </div>
  <div id="out"></div>
<script>
  const filesEl=document.getElementById('files');
  const drop=document.getElementById('drop');
  const thumbs=document.getElementById('thumbs');
  const countEl=document.getElementById('count');
  const out=document.getElementById('out');
  let collected=[];

  function addFiles(list){
    for(const f of list){ if(f && (f.type||'').startsWith('image/')) collected.push(f); }
    render();
  }
  function render(){
    thumbs.innerHTML='';
    collected.forEach(f=>{const i=new Image();i.className='prev';i.src=URL.createObjectURL(f);thumbs.appendChild(i);});
    countEl.textContent=collected.length;
  }

  filesEl.onchange=()=>{ addFiles(filesEl.files); filesEl.value=''; };

  drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('hot');});
  drop.addEventListener('dragleave',e=>{drop.classList.remove('hot');});
  drop.addEventListener('drop',e=>{
    e.preventDefault(); drop.classList.remove('hot');
    const dt=e.dataTransfer; let got=[];
    if(dt.files && dt.files.length){ got=[...dt.files]; }
    else if(dt.items){ for(const it of dt.items){ if(it.kind==='file'){ const f=it.getAsFile(); if(f) got.push(f); } } }
    if(got.length) addFiles(got);
    else out.textContent='这次拖拽没拿到图片文件。微信有时不支持直接拖出——请改用“右键复制图片 → 本页 Ctrl+V 粘贴”。';
  });

  window.addEventListener('paste',e=>{
    const items=(e.clipboardData||{}).items||[]; const got=[];
    for(const it of items){ if(it.kind==='file'){ const f=it.getAsFile(); if(f) got.push(f); } }
    if(got.length){ addFiles(got); out.textContent='已粘贴 '+got.length+' 张'; }
  });

  document.getElementById('clear').onclick=()=>{ collected=[]; render(); out.textContent=''; };

  document.getElementById('send').onclick=async()=>{
    if(!collected.length){ out.textContent='请先选择/拖入/粘贴图片'; return; }
    const fd=new FormData();
    collected.forEach((f,i)=>fd.append('images', f, f.name || ('paste_'+i+'.png')));
    out.textContent='上传中…';
    try{
      const r=await fetch('/api/upload',{method:'POST',body:fd});
      out.textContent=JSON.stringify(await r.json(),null,2);
    }catch(err){ out.textContent='上传失败：'+err; }
  };
</script>
</body></html>"""


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.post("/api/upload")
def upload():
    files = request.files.getlist("images")
    saved = []
    for i, f in enumerate(files):
        name = f.filename or f"img{i}.png"
        # keep original extension, prefix with index to avoid collisions
        base = os.path.basename(name).replace("\\", "_").replace("/", "_")
        path = os.path.join(SAMPLES, f"upload_{i}_{base}")
        f.save(path)
        saved.append(os.path.basename(path))
    return jsonify({"saved": saved, "count": len(saved)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5174)
