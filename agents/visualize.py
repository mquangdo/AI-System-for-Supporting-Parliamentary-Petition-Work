"""Visualize cấu trúc graph của workflow.

In ra mermaid + ascii cho graph duy nhất (workflow()), và lưu thành file .mmd.

Chạy:
    python -m agents.visualize                 # in ra console
    python -m agents.visualize --outdir docs/graphs   # lưu file
"""

import argparse
import sys
from pathlib import Path

from agents.workflow import workflow


def _digest(name, compiled_graph, outdir, save_png):
    """In + lưu mermaid/ascii cho một graph đã compile."""
    data = compiled_graph.get_graph()
    print(f"\n{'='*60}\n{name}\n{'='*60}")
    print("--- Mermaid ---")
    print(data.draw_mermaid())
    try:
        print("--- ASCII ---")
        print(data.draw_ascii())
    except ImportError:
        print("--- ASCII (skipped: missing package `grandalf`) ---")

    if outdir is None:
        return None

    outdir.mkdir(parents=True, exist_ok=True)
    mmd = outdir / f"{name}.mmd"
    mmd.write_text(data.draw_mermaid(), encoding="utf-8")
    saved = [mmd]
    if save_png:
        try:
            png = outdir / f"{name}.png"
            png_data = data.draw_mermaid_png()
            if png_data:
                png.write_bytes(png_data)
                saved.append(png)
        except Exception as exc:  # noqa: BLE001
            print(f"  [lưu ý] Không vẽ được PNG cho {name}: {exc}")
    return saved


def main():
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default=None,
                        help="Thư mục lưu file .mmd (vd docs/graphs).")
    parser.add_argument("--png", action="store_true",
                        help="Kèm xuất PNG (cần net/tiện ích của mermaid).")
    args = parser.parse_args()

    try:
        compiled = workflow()
    except Exception as exc:  # noqa: BLE001
        print(f"[LỖI] Không dựng được graph (kiểm tra LLM/Qdrant/config): {exc}")
        sys.exit(1)

    av = Path(args.outdir) if args.outdir else None
    saved = _digest("workflow", compiled, av, args.png)

    if saved:
        print("\nĐã lưu:")
        for path in saved:
            print(f"  - {path}")


if __name__ == "__main__":
    main()