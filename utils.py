"""🧰 Utility helpers."""
import io
import re
import zipfile
from typing import Dict, Any


def escape_html(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def file_count(session: Dict[str, Any]) -> int:
    return len([k for k in session.get("files", {}) if not k.startswith("__bin__")])


def list_files(session: Dict[str, Any], limit: int = 15):
    files = [k for k in session.get("files", {}) if not k.startswith("__bin__")]
    return files[:limit], max(0, len(files) - limit)


def build_zip(session: Dict[str, Any]) -> io.BytesIO:
    """Session files → ZIP bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in session.get("files", {}).items():
            if name.startswith("__bin__"):
                continue
            is_bin = session["files"].get("__bin__" + name)
            if is_bin and isinstance(content, (bytes, bytearray)):
                z.writestr(name, bytes(content))
            else:
                z.writestr(name, str(content))
    buf.seek(0)
    return buf


def build_single_html(session: Dict[str, Any]):
    """index.html me linked CSS/JS inline karke single HTML."""
    files = session.get("files", {})
    html = files.get("index.html") or files.get("Index.html") or files.get("INDEX.HTML")
    if not html or not isinstance(html, str):
        return None

    def _resolve(path: str):
        path = path.lstrip("./").lstrip("/")
        return files.get(path) or files.get(path.split("/")[-1])

    # Inline CSS
    def repl_css(m):
        href = m.group(1)
        css = _resolve(href)
        if isinstance(css, str):
            return f"<style>\n{css}\n</style>"
        return m.group(0)

    html = re.sub(
        r'<link[^>]*rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)["\'][^>]*/?>',
        repl_css, html, flags=re.IGNORECASE,
    )

    # Inline JS
    def repl_js(m):
        src = m.group(1)
        js = _resolve(src)
        if isinstance(js, str):
            return f"<script>\n{js}\n</script>"
        return m.group(0)

    html = re.sub(
        r'<script[^>]*src=["\']([^"\']+)["\'][^>]*>\s*</script>',
        repl_js, html, flags=re.IGNORECASE,
    )
    return html


def is_text_filename(name: str) -> bool:
    return name.lower().endswith(
        (".html", ".htm", ".css", ".js", ".json", ".txt", ".md", ".svg", ".xml")
    )
