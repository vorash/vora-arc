# vora-arc

Solves ARC-AGI tasks by having a language model write candidate
`transform(grid)` programs and running each one in a
[Vora](https://github.com/vorash/vora) sandbox. Vora runs the code and reports
raw results; this package decides which programs are correct.

## Status

The pipeline is built: `vora-arc solve` samples programs, runs them in
sandboxes, judges and votes, and stores everything in PostgreSQL. `vora-arc
report` turns a stored run into Markdown and charts.

**No real model has run.** The pipeline has only been tested against a local fake
model server (`tests/fake_model.py`) and real Vora sandboxes on one host, so there
are no accuracy or cost results yet. See [docs/model-pipeline.md](docs/model-pipeline.md)
for what is verified and what isn't, and [docs/milestone-1.md](docs/milestone-1.md)
for the harness.

## Run it

```sh
scripts/download_data.sh

export VLLM_URL=http://gpu-host:8000/v1      # an OpenAI-compatible API base
export VLLM_MODEL=<model name>
export VORA_API_URL=… VORA_API_KEY=…
export VORA_ARC_DATABASE_URL=<a PostgreSQL database for this solver>

uv run vora-arc solve --dataset arc1 --split evaluation --limit 100 --samples 64 --refine
GPU_EUR_PER_HOUR=<price> uv run vora-arc report --run <run id printed by solve>
```

`VORA_MAX_CONCURRENCY` caps the sandboxes running at once (default 8). The report
goes to `results/<run id>/`.

## Test it

```sh
uv run pytest           # needs no model, GPU or sandbox
uv run mypy src tests
```

PostgreSQL tests start a throwaway cluster from `initdb` on PATH, or else from the
binaries in the dev dependency `pixeltable-pgserver`. They skip if neither exists.
Tests marked `sandbox` need `VORA_API_URL` and `VORA_API_KEY`.

`dashboards/vora-arc.json` is a Grafana dashboard of Vora's Prometheus metrics.
