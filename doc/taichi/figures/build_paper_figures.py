from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "doc" / "taichi" / "screenshots" / "raw"
OUT = ROOT / "doc" / "taichi" / "screenshots"


@dataclass(frozen=True)
class Source:
    name: str
    width: int
    height: int

    @property
    def uri(self) -> str:
        return (RAW / self.name).as_uri()


TRACE = Source("observatory_trace_icsi_focused.png", 1800, 1348)
TOPIC = Source("observatory_topic_observatory_icsi.png", 1800, 1100)
EXPLORER = Source("observatory_memory_explorer_icsi.png", 1800, 1100)
WALK = Source("observatory_presentation_icsi.png", 1440, 3382)


def crop(src: Source, x: int, y: int, w: int, h: int, scale: float = 1.0, extra_class: str = "") -> str:
    cw = round(w * scale)
    ch = round(h * scale)
    iw = round(src.width * scale)
    ih = round(src.height * scale)
    left = round(-x * scale)
    top = round(-y * scale)
    return f"""
      <div class="crop {extra_class}" style="width:{cw}px;height:{ch}px">
        <img src="{src.uri}" style="width:{iw}px;height:{ih}px;left:{left}px;top:{top}px" />
      </div>
    """


BASE_CSS = """
  :root {
    --ink:#172033;
    --muted:#5d687d;
    --line:#d6deeb;
    --panel:#f8fafc;
    --navy:#172033;
    --l1:#2568c8;
    --l2:#7547c8;
    --l3:#b06b00;
    --ui:#087f78;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:white; color:var(--ink); font-family:Inter, "Segoe UI", Arial, sans-serif; }
  .figure { width:1800px; background:white; padding:28px; }
  .grid { display:grid; gap:18px; align-items:start; }
  .two { grid-template-columns:1fr 1fr; }
  .three { grid-template-columns:repeat(3, 1fr); }
  .panel {
    border:2px solid var(--line);
    border-radius:14px;
    background:var(--panel);
    padding:14px;
    overflow:hidden;
  }
  .panel-label {
    display:flex;
    align-items:baseline;
    gap:10px;
    margin:0 0 10px;
    font-size:22px;
    font-weight:850;
    letter-spacing:0;
  }
  .panel-label span {
    color:var(--muted);
    font-size:15px;
    font-weight:700;
  }
  .crop {
    position:relative;
    overflow:hidden;
    border:1px solid #dbe3ef;
    border-radius:10px;
    background:white;
  }
  .crop img {
    position:absolute;
    display:block;
    max-width:none;
  }
"""


def page(title: str, body: str, extra_css: str = "", height: int | None = None) -> str:
    height_css = f"height:{height}px;" if height else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>{BASE_CSS}{extra_css}</style>
</head>
<body>
  <main class="figure" style="{height_css}">
    {body}
  </main>
</body>
</html>"""


def trace_page() -> str:
    body = f"""
      <section class="grid two">
        <article class="panel">
          <h2 class="panel-label">A. Query and plan <span>settings, counts, and routing state</span></h2>
          {crop(TRACE, 140, 92, 650, 350, 1.06)}
        </article>
        <article class="panel">
          <h2 class="panel-label">B. Topic context <span>L2 state and L3 navigation</span></h2>
          {crop(TRACE, 992, 92, 705, 650, 0.91)}
        </article>
        <article class="panel">
          <h2 class="panel-label">C. L1 evidence <span>source-grounded seeds</span></h2>
          {crop(TRACE, 154, 540, 630, 560, 1.07)}
        </article>
        <article class="panel">
          <h2 class="panel-label">D. Prompt context <span>what is injected before answering</span></h2>
          {crop(TRACE, 932, 823, 820, 305, 1.02)}
        </article>
      </section>
    """
    return page("Retrieval trace paper figure", body, height=1040)


def topic_page() -> str:
    body = f"""
      <section class="panel paper-ui">
        {crop(TOPIC, 260, 142, 1500, 900, 1.0)}
      </section>
    """
    return page("Topic Observatory paper figure", body, height=990)


def explorer_page() -> str:
    body = f"""
      <section class="panel paper-ui">
        {crop(EXPLORER, 260, 82, 1500, 900, 1.0)}
      </section>
    """
    return page("Memory Explorer paper figure", body, height=990)


def walkthrough_page() -> str:
    body = """
      <section class="storyboard">
        <article class="story-card query">
          <div class="step">1</div>
          <h2>Ask a meeting-memory question</h2>
          <p>What should carry over about close microphones and beamforming?</p>
          <div class="query-box">ICSI BMR audio-processing rationale</div>
        </article>
        <article class="story-card evidence">
          <div class="step">2</div>
          <h2>Ground in L1 evidence</h2>
          <div class="mini-card blue">L1-Bmr011-011<br><span>head-mounted microphones</span></div>
          <div class="mini-card blue">L1-Bmr001-046<br><span>delay-and-sum limitation</span></div>
          <div class="mini-card blue">L1-Bmr005-211<br><span>close-talking requirement</span></div>
        </article>
        <article class="story-card topics">
          <div class="step">3</div>
          <h2>Add topic evolution</h2>
          <div class="topic-row amber">L3: audio acquisition and signal processing</div>
          <div class="topic-row purple">L2: audio processing</div>
          <div class="topic-row purple">L2: close talking microphone</div>
          <div class="topic-row purple">L2: hardware limitation</div>
        </article>
        <article class="story-card context">
          <div class="step">4</div>
          <h2>Inspect and correct context</h2>
          <div class="prompt">
            <strong>Formatted prompt context</strong>
            <span>L1 evidence + selected L2 events + L3 map</span>
          </div>
          <div class="sidecar">Sidecar feedback can adjust importance or topic links without overwriting L1.</div>
        </article>
      </section>
    """
    extra_css = """
      .storyboard {
        display:grid;
        grid-template-columns:repeat(4, 1fr);
        gap:18px;
        align-items:stretch;
      }
      .story-card {
        position:relative;
        min-height:515px;
        border:2px solid var(--line);
        border-radius:16px;
        background:#f8fafc;
        padding:24px 22px;
        overflow:hidden;
      }
      .step {
        width:40px;
        height:40px;
        border-radius:999px;
        display:grid;
        place-items:center;
        background:var(--navy);
        color:white;
        font-size:20px;
        font-weight:900;
        margin-bottom:18px;
      }
      .story-card h2 {
        margin:0 0 12px;
        font-size:25px;
        line-height:1.1;
        font-weight:900;
        letter-spacing:0;
      }
      .story-card p {
        margin:0 0 22px;
        color:var(--muted);
        font-size:18px;
        line-height:1.35;
        font-weight:650;
      }
      .query-box {
        margin-top:50px;
        border:2px solid var(--l1);
        border-radius:16px;
        background:#eaf2ff;
        padding:22px;
        color:#17345c;
        font-size:22px;
        font-weight:850;
        line-height:1.25;
      }
      .mini-card {
        border:2px solid #94b8f2;
        border-radius:14px;
        background:#eef5ff;
        padding:17px 18px;
        margin-top:15px;
        font-size:19px;
        font-weight:900;
        color:#17345c;
      }
      .mini-card span {
        display:block;
        margin-top:6px;
        color:#56657a;
        font-size:16px;
        font-weight:700;
      }
      .topic-row {
        border:2px solid;
        border-radius:14px;
        padding:17px 18px;
        margin-top:15px;
        font-size:18px;
        font-weight:850;
      }
      .topic-row.amber {
        border-color:#e4b15c;
        background:#fff3d8;
        color:#724600;
        margin-top:42px;
      }
      .topic-row.purple {
        border-color:#b899ee;
        background:#f2ebff;
        color:#4b278d;
      }
      .prompt {
        margin-top:42px;
        border:2px solid #8bd1c9;
        border-radius:16px;
        background:#e7f8f5;
        padding:22px;
      }
      .prompt strong {
        display:block;
        font-size:20px;
        margin-bottom:12px;
      }
      .prompt span {
        display:block;
        color:#445367;
        font-size:17px;
        font-weight:700;
        line-height:1.4;
      }
      .sidecar {
        margin-top:22px;
        border:2px solid #86cfa8;
        border-radius:16px;
        background:#e8f7ee;
        color:#1c6542;
        padding:20px;
        font-size:17px;
        font-weight:800;
        line-height:1.35;
      }
    """
    return page("ICSI walkthrough paper figure", body, extra_css=extra_css, height=600)


PAGES = {
    "observatory_trace_icsi_focused.png": (trace_page, 1800, 1040),
    "observatory_topic_observatory_icsi.png": (topic_page, 1800, 990),
    "observatory_memory_explorer_icsi.png": (explorer_page, 1800, 990),
    "observatory_presentation_icsi.png": (walkthrough_page, 1800, 600),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for output_name, (make_html, width, height) in PAGES.items():
                html_path = tmp_dir / f"{output_name}.html"
                html_path.write_text(make_html(), encoding="utf-8")
                page_obj = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page_obj.goto(html_path.as_uri(), wait_until="networkidle")
                page_obj.screenshot(path=str(OUT / output_name), full_page=True)
                page_obj.close()
            browser.close()
    for output_name in PAGES:
        print(OUT / output_name)


if __name__ == "__main__":
    main()
