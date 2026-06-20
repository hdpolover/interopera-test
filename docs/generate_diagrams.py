"""Generate two architecture diagrams for the InterOpera Compliance Reporting System."""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

OUT_DIR = '/Users/hendra/Projects/Others/interopera-test/docs'

# ── Palette ────────────────────────────────────────────────────────────────────
BG       = '#f8f9fa'   # near-white background
SLATE    = '#1e2d40'   # primary dark (headers, section labels)
BLUE     = '#2563eb'   # pipeline boxes
BLUE_LT  = '#dbeafe'   # pipeline box fill (light)
GRAY     = '#64748b'   # input/secondary boxes
GRAY_LT  = '#f1f5f9'   # light fill for gray boxes
TEAL     = '#0d7a5f'   # output boxes
TEAL_LT  = '#d1fae5'   # output fill
RED      = '#dc2626'   # LLM only
RED_LT   = '#fee2e2'   # LLM fill
DIVIDER  = '#cbd5e1'   # horizontal rule
TEXT     = '#0f172a'   # body text
SUBTEXT  = '#475569'   # subtitle / secondary text
ARROW    = '#94a3b8'   # arrows


def box(ax, cx, cy, w, h, label, sublabel=None,
        fc=BLUE_LT, ec=BLUE, lw=1.2,
        fontsize=9, subfontsize=7.5, bold=True):
    patch = FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle='round,pad=0.03',
        facecolor=fc, edgecolor=ec, linewidth=lw, zorder=3,
    )
    ax.add_patch(patch)
    if sublabel:
        ax.text(cx, cy + h * 0.15, label, ha='center', va='center',
                color=TEXT, fontsize=fontsize,
                fontweight='bold' if bold else 'normal', zorder=4)
        ax.text(cx, cy - h * 0.20, sublabel, ha='center', va='center',
                color=SUBTEXT, fontsize=subfontsize, style='italic', zorder=4)
    else:
        ax.text(cx, cy, label, ha='center', va='center',
                color=TEXT, fontsize=fontsize,
                fontweight='bold' if bold else 'normal', zorder=4)


def arr(ax, x1, y1, x2, y2):
    ax.annotate(
        '', xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle='->', color=ARROW, lw=1.2,
                        connectionstyle='arc3,rad=0.0'),
        zorder=2,
    )


# ── DIAGRAM 1: Data Flow ───────────────────────────────────────────────────────

def diagram_flow():
    fig, ax = plt.subplots(figsize=(13, 16))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 13)
    ax.set_ylim(0.5, 16.5)
    ax.axis('off')

    # Title
    ax.text(6.5, 16.1, 'InterOpera Compliance Reporting System', ha='center',
            color=SLATE, fontsize=15, fontweight='bold')
    ax.text(6.5, 15.65, 'Architecture · Data Flow', ha='center',
            color=SUBTEXT, fontsize=11)
    ax.axhline(15.35, color=DIVIDER, linewidth=0.8)

    BH = 0.72   # box height
    COL = [2.0, 6.5, 11.0]   # 3 column x-centers

    def section(y, label):
        ax.text(0.25, y, label, ha='left', va='center',
                color=GRAY, fontsize=7.5, fontweight='bold',
                rotation=90 if False else 0)

    # ── Row 1: Inputs ──────────────────────────────────────────────────────────
    y1 = 14.5
    section(y1, 'INPUTS')
    for cx, lbl in zip(COL, ['sample_holdings.csv',
                              'sample_fund_guidelines.pdf',
                              'config/firm_{a,b,c}.yaml']):
        box(ax, cx, y1, 3.6, BH, lbl, fc=GRAY_LT, ec=GRAY, lw=1.0, fontsize=8.5)
    ax.axhline(13.95, color=DIVIDER, linewidth=0.5, linestyle=':')

    # ── Row 2: Ingestion ───────────────────────────────────────────────────────
    y2 = 13.2
    section(y2, 'INGEST')
    box(ax, 3.25, y2, 4.2, BH, 'holdings_parser.py',
        fc=BLUE_LT, ec=BLUE)
    box(ax, 9.75, y2, 4.2, BH, 'guidelines_parser.py',
        sublabel='deterministic pdfplumber parse',
        fc=BLUE_LT, ec=BLUE)
    arr(ax, COL[0], y1 - BH / 2, 3.25, y2 + BH / 2)
    arr(ax, COL[1], y1 - BH / 2, 9.75, y2 + BH / 2)
    ax.axhline(12.7, color=DIVIDER, linewidth=0.5, linestyle=':')

    # ── Row 3: Neo4j Graph ─────────────────────────────────────────────────────
    y3 = 11.8
    section(y3, 'GRAPH')
    box(ax, 6.5, y3, 10.8, BH + 0.15, 'Neo4j Knowledge Graph',
        sublabel='11 node types  ·  limit values on Threshold nodes  ·  provenance on every node',
        fc=BLUE_LT, ec=BLUE, lw=1.5, fontsize=10.5)
    arr(ax, 3.25, y2 - BH / 2, 4.5, y3 + (BH + 0.15) / 2)
    arr(ax, 9.75, y2 - BH / 2, 8.5, y3 + (BH + 0.15) / 2)
    arr(ax, COL[2], y1 - BH / 2, COL[2], y3 + (BH + 0.15) / 2)
    ax.axhline(11.25, color=DIVIDER, linewidth=0.5, linestyle=':')

    # ── Row 4: Compute ─────────────────────────────────────────────────────────
    y4 = 10.3
    section(y4, 'COMPUTE')
    box(ax, 3.25, y4, 4.2, BH, 'config_loader.py → FirmConfig',
        fc=BLUE_LT, ec=BLUE, fontsize=8.5)
    box(ax, 9.75, y4, 4.2, BH, 'engine.py  ComputeEngine',
        fc=BLUE_LT, ec=BLUE, fontsize=8.5)
    arr(ax, 4.5, y3 - (BH + 0.15) / 2, 3.25, y4 + BH / 2)
    arr(ax, 8.5, y3 - (BH + 0.15) / 2, 9.75, y4 + BH / 2)
    arr(ax, 5.35, y4, 7.65, y4)   # config → engine
    ax.axhline(9.8, color=DIVIDER, linewidth=0.5, linestyle=':')

    # ── Row 5: Figures + Narrate + Firewall ────────────────────────────────────
    y5 = 8.8
    section(y5, 'NARRATE')

    # list[Figure]
    box(ax, 2.0, y5, 3.2, BH, 'list[Figure]',
        sublabel='value · status · graph_path · citation',
        fc=BLUE_LT, ec=BLUE, fontsize=8.5)

    # LLM boundary dashed box — wraps narrator only
    bnd = FancyBboxPatch((5.2, y5 - 0.52), 3.8, 1.04,
                          boxstyle='round,pad=0.05',
                          facecolor=RED_LT, edgecolor=RED,
                          linewidth=1.6, linestyle='--', zorder=2)
    ax.add_patch(bnd)
    ax.text(7.1, y5 + 0.62, 'LLM BOUNDARY', ha='center',
            color=RED, fontsize=7.5, fontweight='bold', zorder=5)
    box(ax, 7.1, y5, 3.4, BH, 'narrator.py',
        sublabel='stub or claude-sonnet-4-6',
        fc=RED_LT, ec=RED, fontsize=8.5)

    # Firewall
    box(ax, 11.0, y5, 3.2, BH, 'firewall/checker.py',
        sublabel='6 gates · numeric token check',
        fc=GRAY_LT, ec=GRAY, fontsize=8.5)

    arr(ax, 3.25, y4 - BH / 2, 2.0, y5 + BH / 2)    # compute → figures
    arr(ax, 9.75, y4 - BH / 2, 7.1, y5 + BH / 2)    # engine → narrator
    arr(ax, 9.75, y4 - BH / 2, 11.0, y5 + BH / 2)   # engine → firewall
    arr(ax, 8.8, y5, 9.4, y5)                         # narrator → firewall

    # "Numbers never flow through LLM" callout
    ax.text(6.5, 7.95, '⚠  Numbers never flow through LLM — firewall rejects any mismatch',
            ha='center', va='center', color=RED,
            fontsize=8.5, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.35', facecolor='#fff5f5',
                      edgecolor=RED, linewidth=1.0))
    ax.axhline(7.6, color=DIVIDER, linewidth=0.5, linestyle=':')

    # ── Row 6: Outputs ─────────────────────────────────────────────────────────
    y6 = 6.7
    section(y6, 'OUTPUTS')
    box(ax, 2.0, y6, 3.6, BH, 'report/writer.py → .xlsx',
        fc=TEAL_LT, ec=TEAL, fontsize=8.5)
    box(ax, 6.5, y6, 3.6, BH, 'reconciler.py',
        sublabel='vs answer key',
        fc=TEAL_LT, ec=TEAL, fontsize=8.5)
    box(ax, 11.0, y6, 3.6, BH, 'audit/log.py',
        sublabel='Postgres append-only · SHA-256',
        fc=TEAL_LT, ec=TEAL, fontsize=8.5)

    arr(ax, 2.0, y5 - BH / 2, 2.0, y6 + BH / 2)     # figures → writer
    arr(ax, 3.6, y5, 6.5, y5)                          # figures → reconciler (horizontal)
    arr(ax, 6.5, y5 - BH / 2, 6.5, y6 + BH / 2)
    arr(ax, 11.0, y5 - BH / 2, 11.0, y6 + BH / 2)

    ax.axhline(6.15, color=DIVIDER, linewidth=0.5, linestyle=':')

    # ── Outputs row ─────────────────────────────────────────────────────────────
    y7 = 5.3
    for cx, lbl in zip(COL, ['out/report_firm_{a,b,c}.xlsx',
                              'out/figures_firm_{a,b,c}.json',
                              'postgres:audit_event']):
        box(ax, cx, y7, 3.6, BH * 0.85, lbl,
            fc=GRAY_LT, ec=GRAY, lw=0.8, fontsize=8, bold=False)
    arr(ax, 2.0, y6 - BH / 2, 2.0, y7 + BH * 0.85 / 2)
    arr(ax, 6.5, y6 - BH / 2, 6.5, y7 + BH * 0.85 / 2)
    arr(ax, 11.0, y6 - BH / 2, 11.0, y7 + BH * 0.85 / 2)

    plt.tight_layout(pad=0.6)
    out = f'{OUT_DIR}/architecture_flow.png'
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor=BG)
    plt.close()
    print(f'Saved: {out}')


# ── DIAGRAM 2: LLM Containment Gates ──────────────────────────────────────────

def diagram_layers():
    # Fixed layout — explicit y positions, no computed offsets that can collide.
    # Canvas: 0..13 wide, 0..10 tall.
    fig, ax = plt.subplots(figsize=(13, 10))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 10)
    ax.axis('off')

    TABLE_X   = 0.3
    TABLE_W   = 12.4
    COL_WHERE = 7.9   # x where right column starts

    # ── Title ──────────────────────────────────────────────────────────────────
    ax.text(6.5, 9.65, 'LLM Containment — Six Structural Gates',
            ha='center', color=SLATE, fontsize=14, fontweight='bold')
    ax.text(6.5, 9.28, 'InterOpera Compliance Reporting System',
            ha='center', color=SUBTEXT, fontsize=10)

    # ── Column header band ─────────────────────────────────────────────────────
    HDR_BOT, HDR_TOP = 8.75, 9.05
    hdr = FancyBboxPatch(
        (TABLE_X, HDR_BOT), TABLE_W, HDR_TOP - HDR_BOT,
        boxstyle='round,pad=0.02',
        facecolor='#e2e8f0', edgecolor='none', linewidth=0, zorder=1,
    )
    ax.add_patch(hdr)
    hdr_cy = (HDR_BOT + HDR_TOP) / 2
    ax.text(0.65, hdr_cy, '#',
            ha='center', va='center', color=GRAY, fontsize=8, fontweight='bold')
    ax.text(1.1, hdr_cy, 'Gate',
            ha='left', va='center', color=GRAY, fontsize=8, fontweight='bold')
    ax.text(COL_WHERE + 0.15, hdr_cy, 'Where enforced',
            ha='left', va='center', color=GRAY, fontsize=8, fontweight='bold')

    # ── Data rows — fixed bottom y for each ────────────────────────────────────
    # Order matches the canonical six gates in docs/03_rfc.md §4 and DECISIONS §3.
    gates = [
        ('Static Import Gate',
         'No `import anthropic` in src/compute/',
         'tests/test_llm_containment.py — AST scan'),
        ('Dependency-Injection Gate',
         'ComputeEngine.__init__(driver, config) — no LLM client arg',
         'src/compute/engine.py constructor'),
        ('Report-From-Figures-Only Gate',
         'write_report(figures, path) — no narrative arg',
         'src/report/writer.py'),
        ('Output Firewall',
         'Every narrative number checked against computed set',
         'src/firewall/checker.py — _NUMBER_RE + symmetric norm'),
        ('Human-Approval Gate',
         'PENDING_REVIEW nodes block compute until approved',
         'engine.py _check_gates + _check_limit_node_pending'),
        ('Pure-Code Phase 5',
         'Reconciler & firewall have no LLM imports — deterministic Python',
         'src/reconcile/reconciler.py + src/firewall/checker.py'),
    ]

    ROW_H   = 1.05   # each row height
    GAP     = 0.05   # gap between rows
    PITCH   = ROW_H + GAP
    # First row bottom = just below header
    first_bot = HDR_BOT - GAP - ROW_H

    for i, (name, desc, where) in enumerate(gates):
        bot = first_bot - i * PITCH
        top = bot + ROW_H
        cy  = (bot + top) / 2

        row_fc = '#f0f4ff' if i % 2 == 0 else '#fafafa'
        row_patch = FancyBboxPatch(
            (TABLE_X, bot), TABLE_W, ROW_H,
            boxstyle='round,pad=0.02',
            facecolor=row_fc, edgecolor='none', linewidth=0, zorder=1,
        )
        ax.add_patch(row_patch)

        # Number badge
        circ = plt.Circle((0.65, cy), 0.25, color=BLUE, zorder=3)
        ax.add_patch(circ)
        ax.text(0.65, cy, str(i + 1), ha='center', va='center',
                color='white', fontsize=10, fontweight='bold', zorder=4)

        # Gate name (upper half) + description (lower half)
        ax.text(1.1, cy + 0.17, name,
                ha='left', va='center', color=TEXT,
                fontsize=9.5, fontweight='bold', zorder=2)
        ax.text(1.1, cy - 0.15, desc,
                ha='left', va='center', color=SUBTEXT, fontsize=8, zorder=2)

        # "Where enforced" pill in right column
        pill = FancyBboxPatch(
            (COL_WHERE, cy - 0.25), TABLE_X + TABLE_W - COL_WHERE - 0.1, 0.50,
            boxstyle='round,pad=0.04',
            facecolor='white', edgecolor='#cbd5e1', linewidth=0.7, zorder=2,
        )
        ax.add_patch(pill)
        ax.text(COL_WHERE + 0.15, cy, where,
                ha='left', va='center', color=SUBTEXT,
                fontsize=7.5, style='italic', zorder=3)

    # ── Footer ─────────────────────────────────────────────────────────────────
    ax.text(6.5, 0.3,
            'All six gates verified by automated tests in tests/test_llm_containment.py',
            ha='center', color=GRAY, fontsize=8.5, style='italic')

    plt.tight_layout(pad=0.5)
    out = f'{OUT_DIR}/architecture_layers.png'
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor=BG)
    plt.close()
    print(f'Saved: {out}')


if __name__ == '__main__':
    diagram_flow()
    diagram_layers()
    print('Done.')
