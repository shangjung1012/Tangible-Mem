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
    body = f"""
      <section class="grid three">
        <article class="panel">
          <h2 class="panel-label">A. Topic surface</h2>
          {crop(WALK, 52, 310, 1315, 540, 0.39)}
        </article>
        <article class="panel">
          <h2 class="panel-label">B. Evidence-first trace</h2>
          {crop(WALK, 52, 1116, 1315, 1320, 0.39)}
        </article>
        <article class="panel">
          <h2 class="panel-label">C. Context contrast</h2>
          {crop(WALK, 52, 2736, 1315, 500, 0.39)}
        </article>
      </section>
    """
    return page("ICSI walkthrough paper figure", body, height=700)


PAGES = {
    "observatory_trace_icsi_focused.png": (trace_page, 1800, 1040),
    "observatory_topic_observatory_icsi.png": (topic_page, 1800, 990),
    "observatory_memory_explorer_icsi.png": (explorer_page, 1800, 990),
    "observatory_presentation_icsi.png": (walkthrough_page, 1800, 700),
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
