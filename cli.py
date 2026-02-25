from __future__ import annotations

import argparse
import json
import os


def cmd_run(args: argparse.Namespace) -> None:
    from pipeline import DailyPipeline, PipelineConfig

    pipe = DailyPipeline(
        PipelineConfig(
            db_path=args.db,
            opml_path=args.opml,
            config_dir=args.config,
        )
    )
    pipe.init()
    ingest = pipe.run_ingest()
    anno = pipe.run_annotate_and_topics()
    ranks = pipe.run_rankings()
    print(json.dumps({"ingest": ingest, "annotate": anno, "rankings": ranks}, ensure_ascii=False, indent=2))


def cmd_rank(args: argparse.Namespace) -> None:
    from pipeline import DailyPipeline, PipelineConfig

    pipe = DailyPipeline(
        PipelineConfig(
            db_path=args.db,
            opml_path=args.opml,
            config_dir=args.config,
        )
    )
    pipe.init()
    ranks = pipe.run_rankings()
    print(json.dumps({"rankings": ranks}, ensure_ascii=False, indent=2))


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    os.environ["AINEWS_DB_PATH"] = args.db
    uvicorn.run("api.app:app", host=args.host, port=args.port, reload=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI News Daily app")
    sub = parser.add_subparsers(required=True)

    p_run = sub.add_parser("run", help="run full daily pipeline")
    p_run.add_argument("--db", default="data/ainews.db", help="sqlite db path")
    p_run.add_argument("--opml", default="feeds.opml", help="opml input path")
    p_run.add_argument("--config", default="config", help="config directory")
    p_run.set_defaults(func=cmd_run)

    p_rank = sub.add_parser("rank", help="recompute rankings")
    p_rank.add_argument("--db", default="data/ainews.db", help="sqlite db path")
    p_rank.add_argument("--opml", default="feeds.opml", help="opml input path")
    p_rank.add_argument("--config", default="config", help="config directory")
    p_rank.set_defaults(func=cmd_rank)

    p_serve = sub.add_parser("serve", help="start API server")
    p_serve.add_argument("--db", default="data/ainews.db", help="sqlite db path")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
