"""🎨 Website template builder — Details mode ke liye."""
from utils import escape_html


def build_template(title: str, tagline: str, color: str, layout: str, notes: str) -> str:
    layouts = {
        "hero": f"""
<section class="hero">
  <h1>{escape_html(title)}</h1>
  <p>{escape_html(tagline)}</p>
  <button class="cta">Get Started ✨</button>
</section>
<section class="content"><p>{escape_html(notes)}</p></section>""",

        "portfolio": f"""
<section class="hero small"><h1>{escape_html(title)}</h1><p>{escape_html(tagline)}</p></section>
<section class="grid">
{''.join(f'<div class="card"><div class="thumb">✦</div><h3>Project {i}</h3><p>Short description.</p></div>' for i in range(1, 7))}
</section>
<section class="content"><p>{escape_html(notes)}</p></section>""",

        "blog": f"""
<section class="hero small"><h1>{escape_html(title)}</h1><p>{escape_html(tagline)}</p></section>
<section class="blog">
{''.join(f'<article><h2>Blog Post {i}</h2><p class="meta">Recently · 3 min read</p><p>Lorem ipsum dolor sit amet.</p></article>' for i in range(1, 4))}
</section>
<section class="content"><p>{escape_html(notes)}</p></section>""",

        "card": f"""
<section class="card-page">
  <div class="product-card">
    <div class="product-img">✦</div>
    <h2>{escape_html(title)}</h2>
    <p>{escape_html(tagline)}</p>
    <div class="price">₹ 999</div>
    <button class="cta">Buy Now 🛒</button>
  </div>
  <p class="notes">{escape_html(notes)}</p>
</section>""",
    }

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape_html(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400..900;1,400..900&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Playfair Display',serif;font-style:italic;background:#0a0a0f;color:#e8e8f0;min-height:100vh;
background-image:radial-gradient(circle at 20% 10%, {color}22, transparent 40%),radial-gradient(circle at 80% 80%, {color}11, transparent 40%);}}
.hero{{padding:120px 24px 80px;text-align:center;max-width:900px;margin:0 auto;}}
.hero.small{{padding:80px 24px 40px;}}
.hero h1{{font-size:clamp(2.5rem,7vw,5rem);font-weight:900;background:linear-gradient(135deg,{color},#fff,{color});-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;line-height:1;margin-bottom:16px;}}
.hero p{{color:#a0a0b8;font-size:1.2rem;margin-bottom:32px;}}
.cta{{background:linear-gradient(135deg,{color},#ff6bcb);border:none;padding:16px 36px;border-radius:14px;color:#0a0a0f;font-family:'Playfair Display',serif;font-style:italic;font-weight:700;font-size:1.1rem;cursor:pointer;}}
.content{{max-width:800px;margin:40px auto;padding:0 24px;color:#c0c0d0;line-height:1.7;text-align:center;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px;padding:24px;max-width:1200px;margin:0 auto;}}
.card{{background:rgba(255,255,255,.03);border:1px solid {color}33;border-radius:18px;padding:24px;}}
.thumb{{width:100%;height:140px;border-radius:12px;background:linear-gradient(135deg,{color}44,{color}11);display:flex;align-items:center;justify-content:center;font-size:2.5rem;margin-bottom:16px;color:{color};}}
.blog{{max-width:800px;margin:0 auto;padding:24px;}}
.blog article{{background:rgba(255,255,255,.03);border:1px solid {color}33;border-radius:16px;padding:28px;margin-bottom:18px;}}
.meta{{color:#8080a0;font-size:.85rem;margin-bottom:12px;}}
.card-page{{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:40px 20px;}}
.product-card{{background:rgba(255,255,255,.04);border:1px solid {color}44;border-radius:24px;padding:36px;max-width:420px;width:100%;text-align:center;}}
.product-img{{width:100%;height:220px;border-radius:16px;background:linear-gradient(135deg,{color}66,{color}11);display:flex;align-items:center;justify-content:center;font-size:4rem;color:{color};margin-bottom:24px;}}
.price{{font-size:2rem;font-weight:700;color:{color};margin-bottom:24px;}}
.notes{{max-width:600px;margin:32px auto 0;text-align:center;color:#a0a0b8;line-height:1.7;}}
</style>
</head>
<body>
{layouts.get(layout, layouts["hero"])}
</body>
</html>"""
