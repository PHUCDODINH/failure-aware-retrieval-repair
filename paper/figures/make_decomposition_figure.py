"""Generate the coverage-vs-ranking decomposition figure (Fig. 1).

Print-safe by construction: series are encoded by lightness + hatching (no
hue reliance), direct value labels on every bar, zero line explicit.
Run: python3 paper/figures/make_decomposition_figure.py
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 8,
        "axes.linewidth": 0.6,
        "pdf.fonttype": 42,
    }
)

models = ["Llama-3-8B\n(base 64.7%)", "Qwen2.5-7B\n(base 78.6%)", "GPT-4o-mini\n(base 93.0%, sat.)"]
ranking = [7.5, -1.6, 1.6]
coverage = [14.4, 13.4, -0.5]
ranking_sig = ["p=.065", "ns", "ns"]
coverage_sig = ["***", "***", "ns"]

x = np.arange(len(models))
w = 0.34

fig, ax = plt.subplots(figsize=(3.35, 2.25))

b1 = ax.bar(x - w / 2, ranking, w, label="Ranking headroom",
            color="white", edgecolor="0.25", linewidth=0.7, hatch="////")
b2 = ax.bar(x + w / 2, coverage, w, label="Coverage headroom",
            color="0.35", edgecolor="0.25", linewidth=0.7)

ax.axhline(0, color="0.25", linewidth=0.6)

for bars, sigs in ((b1, ranking_sig), (b2, coverage_sig)):
    for rect, sig in zip(bars, sigs):
        h = rect.get_height()
        va = "bottom" if h >= 0 else "top"
        off = 0.35 if h >= 0 else -0.35
        ax.text(rect.get_x() + rect.get_width() / 2, h + off,
                f"{h:+.1f}\n{sig}", ha="center", va=va, fontsize=6.5,
                linespacing=1.1, color="0.15")

ax.set_xticks(x)
ax.set_xticklabels(models, fontsize=7)
ax.set_ylabel("Repair headroom (pp)")
ax.set_ylim(-6, 20)
ax.spines[["top", "right"]].set_visible(False)
ax.tick_params(length=2, width=0.6)
ax.yaxis.grid(True, color="0.88", linewidth=0.5)
ax.set_axisbelow(True)
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, fontsize=6.5,
          frameon=False, handlelength=1.4, handleheight=1.1,
          columnspacing=1.2, borderaxespad=0.0)

fig.tight_layout(pad=0.3)
fig.savefig("paper/figures/decomposition.pdf")
print("wrote paper/figures/decomposition.pdf")
