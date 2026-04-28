"""
Newsletter builder — synthesis output → HTML 본문.

핵심 후처리:
- markdown → HTML (간이 변환)
- [REF:url] 토큰을 클릭 가능한 (출처) 링크로 치환
"""

from __future__ import annotations

import html
import logging
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..core.config import now_kst, settings
from ..synthesis.pipeline import SynthesisOutput

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

REF_PATTERN = re.compile(r"\[REF:([^\]\s]+)\]")


def _md_to_html(md: str) -> str:
    """경량 markdown → HTML. python-markdown 의존을 피하기 위해 직접 변환."""
    lines = md.splitlines()
    out: list[str] = []
    in_ul = False
    in_ol = False
    in_code = False
    code_buf: list[str] = []

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for line in lines:
        if line.startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                close_lists()
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue

        stripped = line.strip()
        if stripped.startswith("# "):
            close_lists()
            # 이미 헤드라인은 템플릿이 별도로 표시 — 본문에서는 h1 제거
            continue
        if stripped.startswith("## "):
            close_lists()
            out.append(f"<h2>{html.escape(stripped[3:].strip())}</h2>")
            continue
        if stripped.startswith("### "):
            close_lists()
            out.append(f"<h3>{html.escape(stripped[4:].strip())}</h3>")
            continue
        if stripped.startswith("- [ ] ") or stripped.startswith("- [x] "):
            checked = "checked" if stripped.startswith("- [x]") else ""
            text = stripped[6:]
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(
                f'<li><input type="checkbox" {checked} disabled> '
                f'{_inline(html.escape(text))}</li>'
            )
            continue
        if stripped.startswith("- "):
            if not in_ul:
                close_lists()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(html.escape(stripped[2:]))}</li>")
            continue
        if re.match(r"^\d+\.\s", stripped):
            if not in_ol:
                close_lists()
                out.append("<ol>")
                in_ol = True
            text = re.sub(r"^\d+\.\s", "", stripped)
            out.append(f"<li>{_inline(html.escape(text))}</li>")
            continue
        if not stripped:
            close_lists()
            continue
        close_lists()
        out.append(f"<p>{_inline(html.escape(stripped))}</p>")

    close_lists()
    return "\n".join(out)


def _inline(s: str) -> str:
    """`code` + **bold** + REF 처리."""
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def _replace_refs(html_body: str) -> str:
    def repl(m: re.Match) -> str:
        url = m.group(1)
        # html.escape 가 이미 적용되어 &amp; 등이 들어왔을 수 있음
        url = url.replace("&amp;", "&")
        if not url:
            return ""
        safe = html.escape(url, quote=True)
        return f' <a href="{safe}">(출처)</a>'
    return REF_PATTERN.sub(repl, html_body)


def _build_kpi_items(kpis: dict) -> list[dict]:
    items: list[dict] = []
    s = kpis.get("loganalyzer_summary") or {}
    if s:
        items.append({"label": "총 오류", "value": s.get("total_errors", 0)})
        items.append({"label": "Critical", "value": s.get("critical", 0)})
        items.append({"label": "High", "value": s.get("high", 0)})
        items.append({"label": "Open Groups", "value": s.get("open_groups", 0)})
    items.append({"label": "수집 이벤트", "value": kpis.get("total_events", 0)})
    return items


def render_newsletter(syn: SynthesisOutput) -> dict:
    """SynthesisOutput → {subject, headline, html, plain_summary}."""
    subject = (
        f"{settings.insight_subject_prefix} {syn.period_start} ~ {syn.period_end} · "
        f"{syn.headline}"
    )

    body_html = _md_to_html(syn.markdown)
    body_html = _replace_refs(body_html)

    feedback_base = "mailto:" + (settings.gmail_address or "")
    feedback_up = (
        feedback_base + "?subject=" +
        urllib.parse.quote(f"[👍] {subject}")
    )
    feedback_down = (
        feedback_base + "?subject=" +
        urllib.parse.quote(f"[👎] {subject}")
    )

    template = _jinja.get_template("insight_newsletter.html")
    html_full = template.render(
        subject=subject,
        headline=syn.headline,
        period_start=syn.period_start.isoformat(),
        period_end=syn.period_end.isoformat(),
        generated_at=now_kst().strftime("%Y-%m-%d %H:%M KST"),
        kpi_items=_build_kpi_items(syn.kpis),
        body_html=body_html,
        feedback_up=feedback_up,
        feedback_down=feedback_down,
    )

    plain = _build_plain_summary(syn)
    return {
        "subject": subject,
        "headline": syn.headline,
        "html": html_full,
        "plain_summary": plain,
    }


def _build_plain_summary(syn: SynthesisOutput) -> str:
    """RAG 코퍼스 색인용 plain text — markdown 그대로."""
    return f"# {syn.headline}\n\n{syn.markdown}"
