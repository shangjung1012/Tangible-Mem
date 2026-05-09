"""Static JSON viewer for L1 extraction and L2 topic-thread outputs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

THREAD_PROTOTYPE_DIR = Path(__file__).resolve().parents[1] / "prototype_l2_threads"
if str(THREAD_PROTOTYPE_DIR) not in sys.path:
    sys.path.insert(0, str(THREAD_PROTOTYPE_DIR))

from l2_topic_agents import l1_nodes_for_meeting, load_l1_meetings


@dataclass(frozen=True)
class L2DebugViewerResult:
    html_path: Path


def _load_json_if_exists(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _json_for_script(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _build_view_model(*, l1_files: list[Path], l2_dir: Path) -> dict[str, Any]:
    meetings = load_l1_meetings(l1_files)
    l1_nodes = [node for meeting in meetings for node in l1_nodes_for_meeting(meeting)]
    assignments_doc = _load_json_if_exists(l2_dir / "05_l2_l1_assignments.json", {"items": []})
    topics_doc = _load_json_if_exists(l2_dir / "06_l2_topic_threads.json", {"topics": []})
    maintenance_doc = _load_json_if_exists(
        l2_dir / "07_l2_topic_maintenance_report.json",
        {"warnings": []},
    )
    validation_doc = _load_json_if_exists(
        l2_dir / "08_l2_validation_report.json",
        {"valid": False, "errors": ["validation report not found"], "warnings": []},
    )
    l0_doc = _load_json_if_exists(l2_dir / "00_l0_summary_agent_outputs.json", {"meetings": []})

    return {
        "schema": "l2_debug_viewer_v1",
        "l1_files": [str(path) for path in l1_files],
        "l2_dir": str(l2_dir),
        "meetings": meetings,
        "l1_nodes": l1_nodes,
        "l0_summaries": l0_doc.get("meetings", []) if isinstance(l0_doc, dict) else [],
        "assignments": assignments_doc.get("items", []) if isinstance(assignments_doc, dict) else [],
        "topics": topics_doc.get("topics", []) if isinstance(topics_doc, dict) else [],
        "maintenance_warnings": maintenance_doc.get("warnings", [])
        if isinstance(maintenance_doc, dict)
        else [],
        "validation": validation_doc,
    }


def build_l2_debug_viewer(
    *,
    l1_files: list[Path],
    l2_dir: Path,
    out_path: Path,
) -> L2DebugViewerResult:
    view_model = _build_view_model(l1_files=l1_files, l2_dir=l2_dir)
    html = L2_DEBUG_VIEWER_HTML.replace(
        "__L2_DEBUG_VIEW_MODEL__",
        _json_for_script(view_model),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return L2DebugViewerResult(html_path=out_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a static HTML viewer for L1 extraction and L2 topic outputs."
    )
    parser.add_argument(
        "--l1-files",
        nargs="+",
        required=True,
        type=Path,
        help="final_meeting_node.json files used by the L2 run.",
    )
    parser.add_argument(
        "--l2-dir",
        required=True,
        type=Path,
        help="Directory containing 00_l0... through 09_l2... JSON artifacts.",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output HTML path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_l2_debug_viewer(
        l1_files=args.l1_files,
        l2_dir=args.l2_dir,
        out_path=args.out,
    )
    print(f"L2 debug viewer written: {result.html_path}")


L2_DEBUG_VIEWER_HTML = r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>L1 / L2 Memory Debug Viewer</title>
  <style>
    :root{
      --bg:#f6f7f9;--panel:#fff;--ink:#17202a;--muted:#64748b;--line:#d7dee8;
      --soft:#eef2f6;--green:#087568;--green-soft:#def3ee;--blue:#1d4ed8;
      --blue-soft:#e8f0ff;--amber:#9a5b00;--amber-soft:#fff3d6;--red:#b42318;
      --red-soft:#fff0ee;--shadow:0 14px 34px rgba(15,23,42,.07);
      font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink)}
    header{height:68px;background:#10252d;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 22px;gap:16px}
    h1{font-size:18px;margin:0}.sub{color:#b7c9cf;font-size:12px;margin-top:3px}.metrics{display:flex;gap:8px;flex-wrap:wrap}
    .metric{border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.06);border-radius:8px;padding:6px 10px;min-width:76px}
    .metric strong{display:block;font-size:15px}.metric span{font-size:11px;color:#b7c9cf}
    .tabs{display:flex;gap:8px;padding:12px 16px 0}.tab{border:1px solid var(--line);background:#fff;border-radius:8px;padding:9px 13px;cursor:pointer;font:inherit;color:var(--ink)}
    .tab.active{background:#10252d;color:#fff;border-color:#10252d}
    main{display:grid;grid-template-columns:320px minmax(520px,1fr)390px;gap:14px;padding:12px 16px 16px;min-height:calc(100vh - 118px)}
    .panel{background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);overflow:hidden;min-height:0}
    .panelHead{height:48px;padding:10px 12px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:10px}
    .title{font-size:14px;font-weight:760}.body{padding:12px;overflow:auto;max-height:calc(100vh - 178px)}.stack{display:grid;gap:9px}
    input,select{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink);font:inherit;font-size:13px;padding:8px}
    .filters{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}.filters .wide{grid-column:1/-1}
    button.item{width:100%;border:1px solid var(--line);background:#fff;border-radius:8px;padding:9px;text-align:left;cursor:pointer;color:var(--ink)}
    button.item.active{border-color:#75beb4;background:var(--green-soft)}
    .row{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.small{font-size:12px;color:var(--muted)}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
    .chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.chip{display:inline-flex;align-items:center;min-height:22px;padding:3px 7px;border-radius:999px;background:var(--soft);font-size:11px;color:#334155}
    .chip.create,.chip.attach{background:var(--green-soft);color:var(--green)}.chip.retain{background:var(--amber-soft);color:var(--amber)}.chip.suppress,.chip.err{background:var(--red-soft);color:var(--red)}.chip.blue{background:var(--blue-soft);color:var(--blue)}
    .content{font-size:13px;line-height:1.46;margin-top:7px}.grid{display:grid;gap:10px}.node{border:1px solid var(--line);border-radius:8px;background:#fff;padding:10px}
    .node.hot{border-color:#75beb4;background:#fbfffe}.node.warn{border-color:#f0bf5f;background:#fffaf0}.topicHeader{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:8px}
    .l1Row{border-left:4px solid #cbd5e1}.l1Row.attach{border-left-color:var(--green)}.l1Row.create{border-left-color:var(--blue)}.l1Row.retain,.l1Row.suppress{border-left-color:var(--amber)}
    .empty{border:1px dashed #cbd5e1;border-radius:8px;background:#fbfcfe;color:var(--muted);padding:12px;font-size:13px;line-height:1.45}
    pre{white-space:pre-wrap;word-break:break-word;background:#0f172a;color:#dbeafe;border-radius:8px;padding:10px;font-size:11px;max-height:330px;overflow:auto}
    .split{display:grid;grid-template-columns:1fr 1fr;gap:10px}.summary{background:#fbfcfe;border:1px solid var(--line);border-radius:8px;padding:10px}
    @media(max-width:1180px){main{grid-template-columns:300px 1fr}.inspector{grid-column:1/-1}.body{max-height:none}}
    @media(max-width:760px){header{height:auto;display:block;padding:14px 16px}.metrics{margin-top:10px}main{display:block}.panel{margin-bottom:12px}.filters{grid-template-columns:1fr}.split{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <header>
    <div><h1>L1 / L2 Memory Debug Viewer</h1><div class="sub" id="sourceLine"></div></div>
    <div class="metrics" id="metrics"></div>
  </header>
  <nav class="tabs">
    <button class="tab active" data-tab="l1">L1 Extraction</button>
    <button class="tab" data-tab="l2">L2 Topics</button>
  </nav>
  <main>
    <aside class="panel">
      <div class="panelHead"><div class="title" id="leftTitle">L1 Nodes</div><div class="small" id="leftCount"></div></div>
      <div class="body">
        <div class="filters">
          <input class="wide" id="query" placeholder="Search">
          <select id="meetingFilter"></select>
          <select id="typeFilter"></select>
          <select class="wide" id="actionFilter"></select>
        </div>
        <div class="stack" id="leftList"></div>
      </div>
    </aside>
    <section class="panel">
      <div class="panelHead"><div class="title" id="mainTitle">Output</div><div class="small" id="mainSub"></div></div>
      <div class="body" id="mainBody"></div>
    </section>
    <aside class="panel inspector">
      <div class="panelHead"><div class="title">Inspector</div><div class="small" id="selectedId"></div></div>
      <div class="body" id="inspectorBody"></div>
    </aside>
  </main>
<script id="view-data" type="application/json">__L2_DEBUG_VIEW_MODEL__</script>
<script>
const data=JSON.parse(document.getElementById("view-data").textContent);
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const state={tab:"l1",query:"",meeting:"all",type:"all",action:"all",selected:null};
const assignmentByL1=new Map((data.assignments||[]).map(a=>[a.source_l1_id,a]));
const l1ById=new Map((data.l1_nodes||[]).map(n=>[n.obj_id,n]));
const topicsById=new Map((data.topics||[]).map(t=>[t.thread_id,t]));
function actionClass(action){if(action==="create_thread")return"create";if(action==="attach_thread")return"attach";if(action==="suppress_low_value")return"suppress";return"retain";}
function chip(text,cls=""){return `<span class="chip ${cls}">${esc(text)}</span>`}
function metric(label,value){return `<div class="metric"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`}
function sourceLine(){const l2=(data.l2_dir||"").split("/").slice(-2).join("/");$("sourceLine").textContent=`${data.l1_files?.length||0} L1 files · ${l2}`;}
function renderMetrics(){const valid=data.validation?.valid;$("metrics").innerHTML=[metric("meetings",(data.meetings||[]).length),metric("L1 nodes",(data.l1_nodes||[]).length),metric("L2 topics",(data.topics||[]).length),metric("assignments",(data.assignments||[]).length),metric("valid",valid===true?"yes":"check")].join("");}
function setupFilters(){const meetings=["all",...new Set((data.l1_nodes||[]).map(n=>n.meeting_id).filter(Boolean))];$("meetingFilter").innerHTML=meetings.map(x=>`<option value="${esc(x)}">${x==="all"?"All meetings":esc(x)}</option>`).join("");const types=["all",...new Set((data.l1_nodes||[]).map(n=>n.type).filter(Boolean))];$("typeFilter").innerHTML=types.map(x=>`<option value="${esc(x)}">${x==="all"?"All types":esc(x)}</option>`).join("");const actions=["all","create_thread","attach_thread","retain_l1_only","suppress_low_value"];$("actionFilter").innerHTML=actions.map(x=>`<option value="${esc(x)}">${x==="all"?"All actions":esc(x)}</option>`).join("");}
function filteredL1(){const q=state.query.toLowerCase().trim();return (data.l1_nodes||[]).filter(n=>{const a=assignmentByL1.get(n.obj_id)||{};const hay=[n.obj_id,n.meeting_id,n.type,n.content,n.evidence,(n.related_topics||[]).join(" "),a.action,a.reason,a.target_thread_id].join(" ").toLowerCase();return (!q||hay.includes(q))&&(state.meeting==="all"||n.meeting_id===state.meeting)&&(state.type==="all"||n.type===state.type)&&(state.action==="all"||a.action===state.action);});}
function filteredTopics(){const q=state.query.toLowerCase().trim();return (data.topics||[]).filter(t=>{const ids=t.source_l1_ids||[];const l1Text=ids.map(id=>l1ById.get(id)?.content||"").join(" ");const hay=[t.thread_id,t.title,t.description,(t.keywords||[]).join(" "),l1Text].join(" ").toLowerCase();return !q||hay.includes(q);});}
function renderLeft(){if(state.tab==="l1"){const nodes=filteredL1();$("leftTitle").textContent="L1 Nodes";$("leftCount").textContent=`${nodes.length}`;$("leftList").innerHTML=nodes.map(n=>{const a=assignmentByL1.get(n.obj_id)||{};return `<button class="item ${state.selected?.kind==="l1"&&state.selected.id===n.obj_id?"active":""}" data-kind="l1" data-id="${esc(n.obj_id)}"><div class="row"><strong class="mono">${esc(n.obj_id)}</strong><span class="small">${esc(n.meeting_id)}</span></div><div class="chips">${chip(n.type)}${chip(Number(n.importance||0).toFixed(2))}${a.action?chip(a.action,actionClass(a.action)):""}</div><div class="content">${esc(n.content).slice(0,180)}</div></button>`}).join("")||`<div class="empty">No matching L1 nodes.</div>`;}else{const topics=filteredTopics();$("leftTitle").textContent="L2 Topics";$("leftCount").textContent=`${topics.length}`;$("leftList").innerHTML=topics.map(t=>`<button class="item ${state.selected?.kind==="topic"&&state.selected.id===t.thread_id?"active":""}" data-kind="topic" data-id="${esc(t.thread_id)}"><div class="row"><strong>${esc(t.title||"Untitled")}</strong><span class="mono small">${esc(t.thread_id)}</span></div><div class="chips">${chip(`${(t.source_l1_ids||[]).length} L1`,"blue")}${chip(Number(t.importance||0).toFixed(2))}</div><div class="content">${esc(t.description||"").slice(0,180)}</div></button>`).join("")||`<div class="empty">No matching topics.</div>`;}document.querySelectorAll("#leftList .item").forEach(btn=>btn.onclick=()=>{state.selected={kind:btn.dataset.kind,id:btn.dataset.id};render();});}
function renderL1Main(){const selected=state.selected?.kind==="l1"?l1ById.get(state.selected.id):filteredL1()[0];if(selected&&!state.selected)state.selected={kind:"l1",id:selected.obj_id};$("mainTitle").textContent="L1 Extraction Output";$("mainSub").textContent=selected?selected.obj_id:"";if(!selected){$("mainBody").innerHTML=`<div class="empty">No L1 selected.</div>`;return;}const a=assignmentByL1.get(selected.obj_id)||{};$("mainBody").innerHTML=`<div class="grid"><div class="node hot"><div class="row"><strong class="mono">${esc(selected.obj_id)}</strong><span class="small">${esc(selected.meeting_id)}</span></div><div class="chips">${chip(selected.type)}${chip(`importance ${Number(selected.importance||0).toFixed(2)}`)}${(selected.related_topics||[]).map(t=>chip(t,"blue")).join("")}</div><div class="content">${esc(selected.content)}</div></div><div class="split"><div class="node"><div class="title">Evidence</div><div class="content">${esc(selected.evidence||"")}</div></div><div class="node"><div class="title">L2 Assignment</div>${a.action?`<div class="chips">${chip(a.action,actionClass(a.action))}${a.target_thread_id?chip(a.target_thread_id,"blue"):""}${chip(`confidence ${Number(a.confidence||0).toFixed(2)}`)}</div><div class="content">${esc(a.reason||"")}</div>`:`<div class="empty">No assignment found.</div>`}</div></div><div class="node"><div class="title">Raw JSON</div><pre>${esc(JSON.stringify(selected,null,2))}</pre></div></div>`;}
function renderTopicCard(t){const ids=t.source_l1_ids||[];const rows=ids.map(id=>{const n=l1ById.get(id)||{};const a=assignmentByL1.get(id)||{};return `<div class="node l1Row ${actionClass(a.action)}" data-l1="${esc(id)}"><div class="row"><strong class="mono">${esc(id)}</strong><span class="small">${esc(n.meeting_id||"")}</span></div><div class="chips">${chip(n.type||"")}${chip(Number(n.importance||0).toFixed(2))}${a.action?chip(a.action,actionClass(a.action)):""}</div><div class="content">${esc(n.content||"")}</div></div>`}).join("");return `<div class="node hot"><div class="topicHeader"><div><strong>${esc(t.title||"Untitled")}</strong><div class="small mono">${esc(t.thread_id)}</div></div><div class="chips">${chip(`${ids.length} L1`,"blue")}${chip(`importance ${Number(t.importance||0).toFixed(2)}`)}</div></div><div class="content">${esc(t.description||"")}</div><div class="chips">${(t.keywords||[]).slice(0,12).map(k=>chip(k)).join("")}</div></div><div class="grid">${rows||`<div class="empty">No L1 nodes under this topic.</div>`}</div>`}
function renderL2Main(){const selected=state.selected?.kind==="topic"?topicsById.get(state.selected.id):filteredTopics()[0];if(selected&&!state.selected)state.selected={kind:"topic",id:selected.thread_id};$("mainTitle").textContent="L2 Topic Result";$("mainSub").textContent=selected?selected.thread_id:"";if(!selected){$("mainBody").innerHTML=`<div class="empty">No L2 topic selected.</div>`;return;}$("mainBody").innerHTML=renderTopicCard(selected);document.querySelectorAll("[data-l1]").forEach(el=>el.onclick=()=>{state.selected={kind:"l1",id:el.dataset.l1};state.tab="l1";render();});}
function renderInspector(){if(!state.selected){$("selectedId").textContent="";$("inspectorBody").innerHTML=`<div class="empty">Select an L1 node or L2 topic.</div>`;return;}$("selectedId").textContent=state.selected.id;if(state.selected.kind==="l1"){const n=l1ById.get(state.selected.id)||{};const a=assignmentByL1.get(state.selected.id)||{};const t=topicsById.get(a.target_thread_id)||null;$("inspectorBody").innerHTML=`<div class="grid"><div class="summary"><div class="title">Assignment</div><pre>${esc(JSON.stringify(a,null,2))}</pre></div>${t?`<div class="summary"><div class="title">Target Topic</div><pre>${esc(JSON.stringify(t,null,2))}</pre></div>`:""}<div class="summary"><div class="title">L1 Raw</div><pre>${esc(JSON.stringify(n,null,2))}</pre></div></div>`;return;}const t=topicsById.get(state.selected.id)||{};const warnings=(data.maintenance_warnings||[]).filter(w=>(w.thread_ids||[]).includes(t.thread_id));$("inspectorBody").innerHTML=`<div class="grid"><div class="summary"><div class="title">Topic Raw</div><pre>${esc(JSON.stringify(t,null,2))}</pre></div>${warnings.length?`<div class="summary"><div class="title">Warnings</div><pre>${esc(JSON.stringify(warnings,null,2))}</pre></div>`:""}<div class="summary"><div class="title">Validation</div><pre>${esc(JSON.stringify(data.validation,null,2))}</pre></div></div>`;}
function renderWarnings(){const warnings=data.maintenance_warnings||[];const validation=data.validation||{};if(state.tab!=="l2")return "";const err=(validation.errors||[]).map(e=>`<div class="node warn">${esc(e)}</div>`).join("");const warn=warnings.map(w=>`<div class="node warn"><div class="row"><strong>${esc(w.type)}</strong><span class="small">${esc(w.confidence??"")}</span></div><div class="content">${esc(w.reason||"")}</div><div class="chips">${(w.thread_ids||[]).map(id=>chip(id,"blue")).join("")}${w.source_l1_id?chip(w.source_l1_id):""}</div></div>`).join("");return err||warn?`<div class="grid" style="margin-bottom:10px">${err}${warn}</div>`:"";}
function render(){document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active",t.dataset.tab===state.tab));$("actionFilter").style.display=state.tab==="l1"?"block":"none";renderLeft();if(state.tab==="l1"){renderL1Main();}else{renderL2Main();$("mainBody").insertAdjacentHTML("afterbegin",renderWarnings());}renderInspector();}
function init(){sourceLine();renderMetrics();setupFilters();$("query").oninput=e=>{state.query=e.target.value;state.selected=null;render();};$("meetingFilter").onchange=e=>{state.meeting=e.target.value;state.selected=null;render();};$("typeFilter").onchange=e=>{state.type=e.target.value;state.selected=null;render();};$("actionFilter").onchange=e=>{state.action=e.target.value;state.selected=null;render();};document.querySelectorAll(".tab").forEach(btn=>btn.onclick=()=>{state.tab=btn.dataset.tab;state.selected=null;render();});render();}
init();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
