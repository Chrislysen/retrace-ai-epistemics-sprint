"""Draw a deterministic conceptual SVG/PNG; no empirical observations or API."""
from pathlib import Path
import hashlib
import html
import json
import math

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'report/v6i-assets'
WIDTH, HEIGHT = 1800, 850
INK, BORDER, PAPER = '#17202a', '#46505a', '#ffffff'
FONT = Path('C:/Windows/Fonts/arial.ttf')
BOLD = Path('C:/Windows/Fonts/arialbd.ttf')


def main():
    paths = [OUT / ('mechanism-r2.' + ext) for ext in ('svg', 'png', 'json')]
    if any(path.exists() for path in paths):
        raise ValueError('New figure outputs required')
    OUT.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="white"/>']

    def text(x, y, value, size=32, bold=False, anchor='middle'):
        face = ImageFont.truetype(str(BOLD if bold else FONT), size)
        draw.text((x, y), value, font=face, fill=INK, anchor='mm' if anchor == 'middle' else 'lm')
        svg.append(f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="{size}" '
            f'font-weight="{"bold" if bold else "normal"}" text-anchor="{anchor}" dominant-baseline="central" fill="{INK}">{html.escape(value)}</text>')

    def box(bounds, title, lines, *, dashed=False):
        x1, y1, x2, y2 = bounds
        draw.rounded_rectangle(bounds, radius=13, fill='#f5f6f7', outline=BORDER, width=3)
        svg.append(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" rx="13" fill="#f5f6f7" stroke="{BORDER}" stroke-width="3"/>')
        total = 40 * (1 + len(lines))
        start = (y1 + y2 - total) / 2 + 20
        title_size = 34
        while ImageFont.truetype(str(BOLD), title_size).getlength(title) > x2-x1-28:
            title_size -= 1
        text((x1+x2)/2, start, title, title_size, True)
        for i, line in enumerate(lines, 1):
            text((x1+x2)/2, start + 40*i, line, 30)

    def arrow(points, *, dashed=False):
        for a, b in zip(points, points[1:]):
            if dashed:
                length = math.dist(a, b)
                for offset in range(0, int(length), 23):
                    t1, t2 = offset/length, min(offset+13, length)/length
                    draw.line([(a[0]+(b[0]-a[0])*t1, a[1]+(b[1]-a[1])*t1),
                        (a[0]+(b[0]-a[0])*t2, a[1]+(b[1]-a[1])*t2)], fill=BORDER, width=3)
            else:
                draw.line([a, b], fill=BORDER, width=3)
        a, b = points[-2:]
        angle = math.atan2(b[1]-a[1], b[0]-a[0])
        head = [b, (b[0]-18*math.cos(angle-.42), b[1]-18*math.sin(angle-.42)),
            (b[0]-18*math.cos(angle+.42), b[1]-18*math.sin(angle+.42))]
        draw.polygon(head, fill=BORDER)
        dash = ' stroke-dasharray="13 10"' if dashed else ''
        svg.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+f'" fill="none" stroke="{BORDER}" stroke-width="3"{dash}/>')
        svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in head)+f'" fill="{BORDER}"/>')

    box((40, 120, 340, 330), 'Source prose', ['Declared identifiers', 'and exact spans'])
    box((415, 120, 770, 330), 'Source-Proposition IR', ['Boolean scope', 'Negation and lineage'])
    box((845, 120, 1200, 330), 'Candidate family G', ['Declared valid branches', 'Fixed document /', 'passage veto state'])
    box((1300, 35, 1760, 165), 'Decision invariance', ['Invariant / Disputed over G'])
    box((1300, 205, 1760, 335), 'Minimax clarification', ['Yes / No prunes G'])
    box((1300, 375, 1760, 505), 'Withdrawal witnesses', ['Minimal within bounded search'])
    arrow([(340, 225), (415, 225)])
    arrow([(770, 225), (845, 225)])
    for y in (100, 270, 440):
        arrow([(1200, 225), (1245, 225), (1245, y), (1300, y)])
    box((40, 520, 550, 710), 'Adversarial counter-reading', ['Prose + supplied candidate', 'Search for an omitted dependency'])
    arrow([(190, 330), (190, 520)])
    box((650, 520, 1200, 710), 'Proposal admission checks', ['Exact spans + types + registry', 'Nonmutating impact preview'])
    arrow([(550, 615), (650, 615)])
    arrow([(1170, 520), (1170, 330)], dashed=True)
    text(950, 415, 'Proposal only;', 27)
    text(950, 450, 'no automatic adoption', 27)
    text(1520, 615, 'Source location', 30)
    text(1520, 655, 'does not prove entailment.', 30, True)
    text(900, 795, 'Exact within the declared, bounded model; source completeness remains an empirical question.', 30)
    svg.append('</svg>')
    paths[0].write_text('\n'.join(svg)+'\n', encoding='utf-8')
    image.save(paths[1], dpi=(277, 277))
    manifest = {'schema': 'retrace.v6i-mechanism-figure.v1', 'conceptual_only': True,
        'empirical_results': False, 'size_pixels': [WIDTH, HEIGHT], 'generator': 'scripts/draw_v6i_mechanism.py',
        'caption': 'Source-grounded extraction and bounded counterfactual reasoning. The admitted family supports conditional invariance, decision-scoped clarification, and withdrawal witnesses. Adversarial proposals pass location and structural checks before a nonmutating preview; these checks do not certify entailment or exhaustive source interpretation.',
        'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths[:2]}}
    paths[2].write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
