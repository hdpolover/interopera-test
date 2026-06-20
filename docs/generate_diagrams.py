"""
Generate two professional architecture diagrams for the InterOpera Compliance Reporting System.
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe

# ─────────────────────────────────────────────────────────────
# DIAGRAM 1: Data Flow (top-to-bottom)
# ─────────────────────────────────────────────────────────────

def draw_box(ax, x, y, w, h, label, sublabel=None, color='#4a90d9',
             fontsize=10, subfontsize=8, radius=0.04, text_color='white'):
    box = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                         boxstyle=f"round,pad={radius}",
                         linewidth=1.2, edgecolor='white',
                         facecolor=color, zorder=3)
    ax.add_patch(box)
    if sublabel:
        ax.text(x, y + h * 0.15, label, ha='center', va='center',
                color=text_color, fontsize=fontsize, fontweight='bold', zorder=4)
        ax.text(x, y - h * 0.22, sublabel, ha='center', va='center',
                color='#cccccc', fontsize=subfontsize, style='italic', zorder=4,
                wrap=True)
    else:
        ax.text(x, y, label, ha='center', va='center',
                color=text_color, fontsize=fontsize, fontweight='bold', zorder=4)


def arrow(ax, x1, y1, x2, y2, color='#aaaaaa'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color,
                                lw=1.5, connectionstyle='arc3,rad=0.0'),
                zorder=2)


def diagram_flow():
    fig, ax = plt.subplots(figsize=(14, 18))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#1a1a2e')
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 18)
    ax.axis('off')

    # Title
    ax.text(7, 17.4, 'InterOpera Compliance Reporting System', ha='center', va='center',
            color='white', fontsize=16, fontweight='bold')
    ax.text(7, 17.0, 'Architecture Data Flow', ha='center', va='center',
            color='#aaaaff', fontsize=12)

    # ── Row 1: Inputs ──────────────────────────────────────────
    y1 = 15.8
    bh = 0.7
    draw_box(ax, 2.5, y1, 3.2, bh, 'sample_holdings.csv', color='#555577')
    draw_box(ax, 7.0, y1, 3.5, bh, 'sample_fund_guidelines.pdf', color='#555577')
    draw_box(ax, 11.5, y1, 3.2, bh, 'config/firm_{a,b,c}.yaml', color='#555577')

    # Row 1 label
    ax.text(0.3, y1, 'INPUTS', ha='left', va='center', color='#777799',
            fontsize=8, fontweight='bold')

    # ── Row 2: Ingestion ───────────────────────────────────────
    y2 = 14.2
    draw_box(ax, 3.5, y2, 4.0, bh, 'holdings_parser.py', color='#4a90d9')
    draw_box(ax, 10.0, y2, 4.0, bh, 'guidelines_parser.py',
             sublabel='(LLM-optional stub)', color='#4a90d9')

    ax.text(0.3, y2, 'INGEST', ha='left', va='center', color='#777799',
            fontsize=8, fontweight='bold')

    # Arrows row1 → row2
    arrow(ax, 2.5, y1 - bh / 2, 3.2, y2 + bh / 2)
    arrow(ax, 7.0, y1 - bh / 2, 10.0, y2 + bh / 2)

    # ── Row 3: Knowledge Graph ─────────────────────────────────
    y3 = 12.5
    bh3 = 0.85
    draw_box(ax, 7.0, y3, 11.0, bh3,
             'Neo4j Knowledge Graph',
             sublabel='11 node types  ·  MERGE idempotent  ·  provenance on every node',
             color='#7b68ee', fontsize=12)

    ax.text(0.3, y3, 'GRAPH', ha='left', va='center', color='#777799',
            fontsize=8, fontweight='bold')

    arrow(ax, 3.5, y2 - bh / 2, 5.0, y3 + bh3 / 2)
    arrow(ax, 10.0, y2 - bh / 2, 9.0, y3 + bh3 / 2)
    # config arrow
    arrow(ax, 11.5, y1 - bh / 2, 11.5, y3 + bh3 / 2)

    # ── Row 4: Compute ─────────────────────────────────────────
    y4 = 10.9
    draw_box(ax, 3.5, y4, 4.0, bh, 'config_loader.py → FirmConfig', color='#50c878',
             text_color='#1a1a2e')
    draw_box(ax, 10.0, y4, 4.0, bh, 'engine.py  ComputeEngine', color='#50c878',
             text_color='#1a1a2e')

    ax.text(0.3, y4, 'COMPUTE', ha='left', va='center', color='#777799',
            fontsize=8, fontweight='bold')

    arrow(ax, 6.0, y3 - bh3 / 2, 3.5, y4 + bh / 2)
    arrow(ax, 8.0, y3 - bh3 / 2, 10.0, y4 + bh / 2)
    # config_loader → engine
    arrow(ax, 5.5, y4, 8.0, y4)

    # ── Row 5: Mid-outputs ─────────────────────────────────────
    y5 = 9.1
    draw_box(ax, 2.2, y5, 3.5, bh, 'list[Figure]',
             sublabel='value · status · graph_path · citation',
             color='#f0a500', text_color='#1a1a2e')

    # LLM boundary dashed box
    llm_box = FancyBboxPatch((6.0, y5 - 0.55), 4.0, 1.1,
                              boxstyle="round,pad=0.08",
                              linewidth=2, linestyle='--',
                              edgecolor='#e74c3c', facecolor='none', zorder=2)
    ax.add_patch(llm_box)
    ax.text(8.0, y5 + 0.62, 'LLM BOUNDARY', ha='center', va='bottom',
            color='#e74c3c', fontsize=8, fontweight='bold', zorder=5)

    draw_box(ax, 8.0, y5, 3.6, bh, 'narrator.py',
             sublabel='(stub or claude-haiku)', color='#e74c3c')

    draw_box(ax, 12.5, y5, 3.0, bh, 'firewall/checker.py',
             sublabel='6 gates · numeric token check', color='#c0392b')

    # "Numbers never flow through LLM" note
    ax.text(7, 8.2, '⚠  Numbers never flow through LLM', ha='center', va='center',
            color='#ff6b6b', fontsize=10, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#2d0a0a',
                      edgecolor='#e74c3c', linewidth=1.5))

    ax.text(0.3, y5, 'NARRATE', ha='left', va='center', color='#777799',
            fontsize=8, fontweight='bold')

    arrow(ax, 5.0, y4 - bh / 2, 2.2, y5 + bh / 2)
    arrow(ax, 10.0, y4 - bh / 2, 8.0, y5 + bh / 2)
    arrow(ax, 10.0, y4 - bh / 2, 12.5, y5 + bh / 2)
    arrow(ax, 9.8, y5, 11.0, y5)    # narrator → checker

    # ── Row 6: Final outputs ───────────────────────────────────
    y6 = 6.9
    draw_box(ax, 2.2, y6, 3.5, bh, 'report/writer.py → .xlsx', color='#00897b')
    draw_box(ax, 7.0, y6, 3.5, bh, 'reconciler.py',
             sublabel='vs answer key', color='#00897b')
    draw_box(ax, 11.8, y6, 3.5, bh, 'audit/log.py',
             sublabel='Postgres append-only\nSHA-256 hash chain', color='#00897b')

    ax.text(0.3, y6, 'OUTPUTS', ha='left', va='center', color='#777799',
            fontsize=8, fontweight='bold')

    arrow(ax, 2.2, y5 - bh / 2, 2.2, y6 + bh / 2)
    arrow(ax, 8.0, y5 - bh / 2, 7.0, y6 + bh / 2)
    arrow(ax, 12.5, y5 - bh / 2, 11.8, y6 + bh / 2)
    # figures → reconciler
    arrow(ax, 3.9, y5, 7.0, y5)
    arrow(ax, 5.5, y6, 5.3, y6)

    # Separator lines between rows
    for ysep in [15.1, 13.4, 11.7, 9.85, 7.7]:
        ax.axhline(ysep, color='#333355', linewidth=0.5, linestyle=':', zorder=1)

    # Legend
    legend_y = 6.0
    for i, (label, color) in enumerate([
        ('Input files', '#555577'),
        ('Parsers', '#4a90d9'),
        ('Knowledge Graph', '#7b68ee'),
        ('Compute', '#50c878'),
        ('LLM / Narrative', '#e74c3c'),
        ('Outputs', '#00897b'),
        ('Figures', '#f0a500'),
    ]):
        lx = 1.0 + i * 1.9
        rect = FancyBboxPatch((lx - 0.65, legend_y - 0.2), 1.3, 0.4,
                               boxstyle="round,pad=0.05",
                               facecolor=color, edgecolor='white', linewidth=0.8)
        ax.add_patch(rect)
        tc = '#1a1a2e' if color in ('#50c878', '#f0a500') else 'white'
        ax.text(lx, legend_y, label, ha='center', va='center',
                color=tc, fontsize=7, fontweight='bold')

    plt.tight_layout(pad=0.5)
    out = '/Users/hendra/Projects/Others/interopera-test/docs/architecture_flow.png'
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    print(f'Saved: {out}')


# ─────────────────────────────────────────────────────────────
# DIAGRAM 2: LLM Containment Gates (horizontal lanes)
# ─────────────────────────────────────────────────────────────

def diagram_layers():
    fig, ax = plt.subplots(figsize=(14, 10))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#1a1a2e')
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 10)
    ax.axis('off')

    # Title
    ax.text(7, 9.55, 'LLM Containment — Six Structural Gates', ha='center', va='center',
            color='white', fontsize=15, fontweight='bold')
    ax.text(7, 9.15, 'InterOpera Compliance Reporting System', ha='center', va='center',
            color='#aaaaff', fontsize=10)

    gates = [
        {
            'num': '1',
            'name': 'Static Import Gate',
            'desc': 'No `import anthropic` in `src/compute/`',
            'where': 'AST scan in test_llm_containment.py',
            'color': '#e74c3c',
        },
        {
            'num': '2',
            'name': 'Dependency-Injection Gate',
            'desc': 'ComputeEngine.__init__(driver, config) — no LLM client arg',
            'where': 'src/compute/engine.py constructor',
            'color': '#e67e22',
        },
        {
            'num': '3',
            'name': 'Report-From-Figures-Only Gate',
            'desc': 'write_report(figures, path) — no narrative arg',
            'where': 'src/report/writer.py',
            'color': '#f39c12',
        },
        {
            'num': '4',
            'name': 'Human-Approval Gate',
            'desc': 'PENDING_REVIEW nodes block compute until approved',
            'where': 'engine.py Gate 1 + Gate 2',
            'color': '#27ae60',
        },
        {
            'num': '5',
            'name': 'Reconcile Gate',
            'desc': 'Reconciler has no LLM imports — all deterministic Python',
            'where': 'src/reconcile/reconciler.py',
            'color': '#2980b9',
        },
        {
            'num': '6',
            'name': 'Numeric Token Firewall',
            'desc': 'Every narrative number checked against computed set',
            'where': 'src/firewall/checker.py — _NUMBER_RE + symmetric normalization',
            'color': '#8e44ad',
        },
    ]

    n = len(gates)
    # Vertical range for the gates section
    y_top = 8.7
    y_bot = 0.9
    lane_h = (y_top - y_bot) / n
    lx_start = 0.6
    lx_end = 10.8
    lane_w = lx_end - lx_start

    # LLM source box (top right)
    llm_x = 12.5
    llm_y_top = 8.5
    llm_box = FancyBboxPatch((llm_x - 0.85, llm_y_top - 0.35), 1.7, 0.7,
                              boxstyle="round,pad=0.06",
                              facecolor='#c0392b', edgecolor='white', linewidth=1.5, zorder=3)
    ax.add_patch(llm_box)
    ax.text(llm_x, llm_y_top, 'LLM\n(claude-haiku)', ha='center', va='center',
            color='white', fontsize=9, fontweight='bold', zorder=4)

    # Output box (bottom right)
    out_x = 12.5
    out_y = 1.2
    out_box = FancyBboxPatch((out_x - 1.1, out_y - 0.42), 2.2, 0.85,
                              boxstyle="round,pad=0.06",
                              facecolor='#27ae60', edgecolor='white', linewidth=1.5, zorder=3)
    ax.add_patch(out_box)
    ax.text(out_x, out_y, 'xlsx Report\n+ Audit Log', ha='center', va='center',
            color='white', fontsize=9, fontweight='bold', zorder=4)

    # Vertical arrow on right: LLM → gates → output
    ax.annotate('', xy=(llm_x, out_y + 0.43), xytext=(llm_x, llm_y_top - 0.35),
                arrowprops=dict(arrowstyle='->', color='#aaaaaa', lw=2,
                                connectionstyle='arc3,rad=0.0'), zorder=2)

    for i, gate in enumerate(gates):
        lane_y_top = y_top - i * lane_h
        lane_y_bot = lane_y_top - lane_h
        cy = (lane_y_top + lane_y_bot) / 2

        # Lane background
        bg = FancyBboxPatch((lx_start, lane_y_bot + 0.04), lane_w, lane_h - 0.08,
                             boxstyle="round,pad=0.04",
                             facecolor=gate['color'] + '22',
                             edgecolor=gate['color'],
                             linewidth=1.5, zorder=2)
        ax.add_patch(bg)

        # Gate number circle
        circle = plt.Circle((lx_start + 0.45, cy), 0.28, color=gate['color'], zorder=3)
        ax.add_patch(circle)
        ax.text(lx_start + 0.45, cy, gate['num'], ha='center', va='center',
                color='white', fontsize=13, fontweight='bold', zorder=4)

        # Gate name
        ax.text(lx_start + 1.1, cy + 0.13, gate['name'],
                ha='left', va='center', color='white',
                fontsize=11, fontweight='bold', zorder=3)

        # Description
        ax.text(lx_start + 1.1, cy - 0.08, gate['desc'],
                ha='left', va='center', color='#dddddd',
                fontsize=8.5, zorder=3)

        # Where enforced
        where_x = lx_end - 0.1
        where_box = FancyBboxPatch((where_x - 2.6, cy - 0.22), 2.6, 0.44,
                                    boxstyle="round,pad=0.04",
                                    facecolor='#ffffff11',
                                    edgecolor=gate['color'] + 'aa',
                                    linewidth=0.8, zorder=3)
        ax.add_patch(where_box)
        ax.text(where_x - 1.3, cy, gate['where'],
                ha='center', va='center', color='#bbbbff',
                fontsize=7.5, style='italic', zorder=4,
                wrap=True)

        # Barrier line on the right side arrow
        barrier_y = lane_y_top - 0.04
        if i < n - 1:
            ax.plot([llm_x - 0.25, llm_x + 0.25], [barrier_y, barrier_y],
                    color=gate['color'], lw=2.5, zorder=3, solid_capstyle='round')
            ax.text(llm_x - 0.6, barrier_y, '▶', ha='right', va='center',
                    color=gate['color'], fontsize=10, zorder=4)

    # Column headers
    ax.text(lx_start + 0.45, y_top + 0.15, '#', ha='center', va='bottom',
            color='#888888', fontsize=8, fontweight='bold')
    ax.text(lx_start + 1.1, y_top + 0.15, 'Gate Name & Description', ha='left', va='bottom',
            color='#888888', fontsize=8, fontweight='bold')
    ax.text(lx_end - 1.3, y_top + 0.15, 'Where Enforced', ha='center', va='bottom',
            color='#888888', fontsize=8, fontweight='bold')

    # Divider
    ax.axhline(y_top + 0.05, xmin=0.04, xmax=0.78,
               color='#333355', linewidth=0.8, linestyle='--')

    # Footer note
    ax.text(7, 0.45, 'All six gates are verified by automated tests in tests/test_llm_containment.py',
            ha='center', va='center', color='#888888', fontsize=9, style='italic')

    plt.tight_layout(pad=0.3)
    out = '/Users/hendra/Projects/Others/interopera-test/docs/architecture_layers.png'
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    print(f'Saved: {out}')


if __name__ == '__main__':
    diagram_flow()
    diagram_layers()
    print('Done.')
