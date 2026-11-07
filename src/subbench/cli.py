from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from .benchmark import MihomoBenchmark, validate_clash_config, write_mihomo_config
from .models import Node
from .output import prepare_names, write_outputs
from .parsers import count_raw_entries, parse_document
from .prefilter import aliyun_tcp_prefilter, normalize_aliyun_url, tcp_prefilter
from .sources import fetch_sources, load_sources


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _filter_benchmarked_nodes(
    nodes: list[Node],
    max_latency: int,
    min_speed: float,
    require_speed: bool = True,
) -> list[Node]:
    return [
        node
        for node in nodes
        if node.error is None
        and node.latency_ms is not None
        and node.latency_ms <= max_latency
        and (
            not require_speed
            or (node.speed_mbps is not None and node.speed_mbps >= min_speed)
        )
    ]


def _print_run_summary(
    *,
    started_at: float,
    sources_configured: int,
    sources_successful: int,
    raw_nodes: int,
    parsed_nodes: int,
    duplicates_removed: int,
    nodes_tested: int,
    nodes_alive: int,
    nodes_failed: int,
    final_nodes: int,
) -> None:
    print(f"Sources configured: {sources_configured}")
    print(f"Sources successful: {sources_successful}")
    print(f"Sources failed: {sources_configured - sources_successful}")
    print(f"Raw nodes: {raw_nodes}")
    print(f"Parsed nodes: {parsed_nodes}")
    print(f"Duplicates removed: {duplicates_removed}")
    print(f"Nodes tested: {nodes_tested}")
    print(f"Nodes alive: {nodes_alive}")
    print(f"Nodes failed: {nodes_failed}")
    print(f"Final nodes: {final_nodes}")
    print(f"Runtime: {time.monotonic() - started_at:.1f}s", flush=True)


def _publish_staged_outputs(staged_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("v2ray.txt", "v2ray-raw.txt", "report.json", "index.html"):
        os.replace(staged_dir / name, output_dir / name)
    os.replace(staged_dir / "clash.yaml", output_dir / "clash.yaml")


def run(args: argparse.Namespace) -> int:
    started_at = time.monotonic()
    source_specs = load_sources(args.sources)
    if not source_specs:
        _print_run_summary(
            started_at=started_at,
            sources_configured=0,
            sources_successful=0,
            raw_nodes=0,
            parsed_nodes=0,
            duplicates_removed=0,
            nodes_tested=0,
            nodes_alive=0,
            nodes_failed=0,
            final_nodes=0,
        )
        raise RuntimeError("No sources are configured.")

    source_results = fetch_sources(
        source_specs,
        timeout_seconds=_float_env("SOURCE_TIMEOUT_SECONDS", 60.0),
        workers=_int_env("FETCH_WORKERS", 4),
        retries=_int_env("SOURCE_RETRIES", 3),
        retry_backoff_seconds=_float_env("SOURCE_RETRY_BACKOFF_SECONDS", 2.0),
    )
    nodes: list[Node] = []
    source_errors: list[dict[str, str]] = []
    skipped_nodes: list[str] = []
    raw_nodes = 0
    sources_successful = 0
    for result in source_results:
        if result.error:
            source_errors.append({"source": result.source.name, "error": result.error})
            continue
        text = result.text or ""
        raw_nodes += count_raw_entries(text)
        try:
            parsed = parse_document(text, result.source.name, skipped_nodes)
        except Exception as exc:
            source_errors.append({"source": result.source.name, "error": type(exc).__name__})
            continue
        if not parsed:
            source_errors.append({"source": result.source.name, "error": "no_supported_nodes"})
            continue
        sources_successful += 1
        nodes.extend(parsed)

    parsed_nodes = len(nodes)
    unique: dict[str, Node] = {}
    for node in nodes:
        unique.setdefault(node.canonical_key(), node)
    duplicates_removed = parsed_nodes - len(unique)
    nodes = list(unique.values())
    max_nodes = _int_env("MAX_NODES", 0)
    if max_nodes > 0:
        nodes = nodes[:max_nodes]

    nodes_tested = 0
    nodes_alive = 0
    nodes_failed = 0
    final_nodes = 0
    if sources_successful == 0 or parsed_nodes == 0 or not nodes:
        _print_run_summary(
            started_at=started_at,
            sources_configured=len(source_specs),
            sources_successful=sources_successful,
            raw_nodes=raw_nodes,
            parsed_nodes=parsed_nodes,
            duplicates_removed=duplicates_removed,
            nodes_tested=0,
            nodes_alive=0,
            nodes_failed=0,
            final_nodes=0,
        )
        raise RuntimeError("No source produced supported nodes.")
    if args.skip_benchmark:
        _print_run_summary(
            started_at=started_at,
            sources_configured=len(source_specs),
            sources_successful=sources_successful,
            raw_nodes=raw_nodes,
            parsed_nodes=parsed_nodes,
            duplicates_removed=duplicates_removed,
            nodes_tested=0,
            nodes_alive=0,
            nodes_failed=0,
            final_nodes=0,
        )
        raise RuntimeError("Mihomo testing is required before a subscription can be published.")

    mihomo = Path(args.mihomo)
    if not mihomo.exists():
        _print_run_summary(
            started_at=started_at,
            sources_configured=len(source_specs),
            sources_successful=sources_successful,
            raw_nodes=raw_nodes,
            parsed_nodes=parsed_nodes,
            duplicates_removed=duplicates_removed,
            nodes_tested=0,
            nodes_alive=0,
            nodes_failed=0,
            final_nodes=0,
        )
        raise RuntimeError("Mihomo binary is unavailable.")

    if _bool_env("TCP_PREFILTER_ENABLED", False):
        nodes = tcp_prefilter(
            nodes,
            timeout_seconds=_float_env("TCP_CONNECT_TIMEOUT_SECONDS", 3.0),
            workers=_int_env("TCP_PREFILTER_WORKERS", 128),
            attempts=_int_env("TCP_CONNECT_ATTEMPTS", 2),
        )
    if not nodes:
        _print_run_summary(
            started_at=started_at,
            sources_configured=len(source_specs),
            sources_successful=sources_successful,
            raw_nodes=raw_nodes,
            parsed_nodes=parsed_nodes,
            duplicates_removed=duplicates_removed,
            nodes_tested=0,
            nodes_alive=0,
            nodes_failed=parsed_nodes,
            final_nodes=0,
        )
        raise RuntimeError("No nodes reached Mihomo testing.")

    for node in nodes:
        node.metadata.setdefault("original_name", node.name)
    prepare_names(nodes)
    nodes_tested = len(nodes)
    speed_test_enabled = _bool_env("SPEED_TEST_ENABLED", False)
    workdir = Path(args.workdir)
    try:
        with MihomoBenchmark(
            binary=mihomo,
            workdir=workdir,
            nodes=nodes,
            latency_url=os.environ.get(
                "LATENCY_TEST_URL", "https://www.gstatic.com/generate_204"
            ),
            speed_url=os.environ.get(
                "SPEED_TEST_URL",
                "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/release/country.mmdb",
            ),
            geo_url=os.environ.get(
                "GEOIP_TEST_URLS",
                "https://www.cloudflare.com/cdn-cgi/trace,https://api.country.is/",
            ),
            timeout_ms=_int_env("LATENCY_TIMEOUT_MS", 5000),
            speed_bytes=_int_env("SPEED_TEST_BYTES", 1_000_000),
            speed_limit=_int_env("SPEED_TEST_LIMIT", 0),
            speed_timeout_seconds=_int_env("SPEED_TIMEOUT_SECONDS", 8),
            workers=_int_env("BENCHMARK_WORKERS", 48),
            speed_enabled=speed_test_enabled,
            latency_attempts=_int_env("LATENCY_TEST_ATTEMPTS", 1),
        ) as benchmark:
            write_mihomo_config(workdir / "mihomo-nodes.yaml", nodes)
            nodes = benchmark.benchmark(nodes)
    except Exception:
        _print_run_summary(
            started_at=started_at,
            sources_configured=len(source_specs),
            sources_successful=sources_successful,
            raw_nodes=raw_nodes,
            parsed_nodes=parsed_nodes,
            duplicates_removed=duplicates_removed,
            nodes_tested=nodes_tested,
            nodes_alive=0,
            nodes_failed=nodes_tested,
            final_nodes=0,
        )
        raise

    nodes = _filter_benchmarked_nodes(
        nodes,
        _int_env("MAX_LATENCY_MS", 5000),
        _float_env("MIN_SPEED_MBPS", 0.1),
        require_speed=speed_test_enabled,
    )
    if _bool_env("ALIYUN_FC_ENABLED", False):
        aliyun_fc_url = normalize_aliyun_url(os.environ.get("ALIYUN_FC_URL", ""))
        if aliyun_fc_url and nodes:
            nodes = aliyun_tcp_prefilter(
                nodes,
                url=aliyun_fc_url,
                timeout_seconds=_float_env("ALIYUN_FC_TIMEOUT_SECONDS", 10.0),
                interval_seconds=_float_env("ALIYUN_FC_INTERVAL_SECONDS", 0.2),
                interval_jitter_seconds=_float_env("ALIYUN_FC_JITTER_SECONDS", 0.1),
                max_consecutive_errors=_int_env("ALIYUN_FC_MAX_CONSECUTIVE_ERRORS", 3),
                workers=_int_env("ALIYUN_FC_WORKERS", 10),
            )
    nodes.sort(
        key=lambda node: (
            node.speed_mbps is None,
            -(node.speed_mbps or 0),
            node.latency_ms is None,
            node.latency_ms or 10**9,
        )
    )
    nodes_alive = len(nodes)
    nodes_failed = max(0, nodes_tested - nodes_alive)
    max_output_nodes = _int_env("MAX_OUTPUT_NODES", 0)
    if max_output_nodes > 0:
        nodes = nodes[:max_output_nodes]
    final_nodes = len(nodes)

    if nodes_alive == 0 or final_nodes == 0:
        _print_run_summary(
            started_at=started_at,
            sources_configured=len(source_specs),
            sources_successful=sources_successful,
            raw_nodes=raw_nodes,
            parsed_nodes=parsed_nodes,
            duplicates_removed=duplicates_removed,
            nodes_tested=nodes_tested,
            nodes_alive=nodes_alive,
            nodes_failed=nodes_failed,
            final_nodes=0,
        )
        raise RuntimeError("No nodes passed Mihomo testing and output filters; keeping the previous subscription.")

    output_dir = Path(args.output)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(prefix=".subbench-stage-", dir=str(output_dir.parent)) as stage_root:
            staged_dir = Path(stage_root) / "public"
            write_outputs(staged_dir, nodes, source_errors)
            validate_clash_config(mihomo, staged_dir / "clash.yaml", workdir)
            _publish_staged_outputs(staged_dir, output_dir)
    except Exception:
        _print_run_summary(
            started_at=started_at,
            sources_configured=len(source_specs),
            sources_successful=sources_successful,
            raw_nodes=raw_nodes,
            parsed_nodes=parsed_nodes,
            duplicates_removed=duplicates_removed,
            nodes_tested=nodes_tested,
            nodes_alive=nodes_alive,
            nodes_failed=nodes_failed,
            final_nodes=final_nodes,
        )
        raise

    _print_run_summary(
        started_at=started_at,
        sources_configured=len(source_specs),
        sources_successful=sources_successful,
        raw_nodes=raw_nodes,
        parsed_nodes=parsed_nodes,
        duplicates_removed=duplicates_removed,
        nodes_tested=nodes_tested,
        nodes_alive=nodes_alive,
        nodes_failed=nodes_failed,
        final_nodes=final_nodes,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", default="run")
    parser.add_argument("--sources", type=Path, default=Path("config/sources.txt"))
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--workdir", type=Path, default=Path(".work"))
    parser.add_argument("--mihomo", type=Path, default=Path(".bin/mihomo"))
    parser.add_argument("--skip-benchmark", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run(args)
    except Exception:
        print("Build failed; existing subscription outputs were retained.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
