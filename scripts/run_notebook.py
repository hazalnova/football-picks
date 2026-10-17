"""Run one notebook from top to bottom, the same as "Run all" in Colab.

The GitHub Actions workflow runs this from the data folder, so each notebook reads and writes its logs there:

    cd data
    python ../scripts/run_notebook.py ../notebooks/nfl_game_model.ipynb

A copy of the notebook with all its output is saved in the runs folder. On GitHub, the printed output also goes to
the run's summary page, and the copies can be downloaded from the run as "notebooks-with-output".
"""
import os
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError


def printed_text(nb):
    """Everything the notebook printed, plus any error, in order."""
    out = []
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        for o in cell.get("outputs", []):
            if o.get("output_type") == "stream" and o.get("name") == "stdout":
                out.append(o["text"])
            elif o.get("output_type") == "error":
                out.append(f"\n{o['ename']}: {o['evalue']}\n")
    return "".join(out)


def main(path):
    path = Path(path)
    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(nb, timeout=1800, kernel_name="python3", resources={"metadata": {"path": os.getcwd()}})
    error = None
    try:
        client.execute()
    except CellExecutionError as e:
        error = e

    runs = Path(os.environ.get("RUNS_DIR", "../runs"))
    runs.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, runs / path.name)

    text = printed_text(nb)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            status = "stopped with an error" if error else "finished"
            f.write(f"<details{' open' if error else ''}><summary><b>{path.stem}</b> {status}</summary>\n\n"
                    f"```\n{text[-60000:]}\n```\n</details>\n\n")
    if error:
        print(f"{path.name} stopped with an error:\n{error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
