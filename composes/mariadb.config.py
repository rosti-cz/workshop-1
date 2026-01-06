#!/usr/bin/env python3
"""
Generate a basic MariaDB 12 my.cnf snippet sized to a memory budget.

Goal: produce a conservative starting config that is unlikely to OOM under a
memory limit by budgeting global buffers + modeled active per-connection memory.

Examples:
  ./gen_mycnf.py 8
  ./gen_mycnf.py 4 --max-connections 150
  ./gen_mycnf.py 16 --active-frac 0.15 --profile web

Output is printed to stdout.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    sort_buffer_mib: int
    join_buffer_mib: int
    read_buffer_mib: int
    read_rnd_buffer_mib: int
    tmp_table_mib: int
    base_connections: int


PROFILES: dict[str, Profile] = {
    "general": Profile(
        name="general",
        sort_buffer_mib=4,
        join_buffer_mib=4,
        read_buffer_mib=1,
        read_rnd_buffer_mib=1,
        tmp_table_mib=64,
        base_connections=120,
    ),
    "web": Profile(
        name="web",
        sort_buffer_mib=2,
        join_buffer_mib=2,
        read_buffer_mib=1,
        read_rnd_buffer_mib=1,
        tmp_table_mib=32,
        base_connections=200,
    ),
}


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def fmt_mib(mib: int) -> str:
    return f"{mib}M"


def compute_max_connections(budget_mib: float, profile: Profile) -> int:
    # Rough scaling: +1 connection per 64 MiB, plus a profile baseline.
    scale = int(budget_mib / 64.0)
    return clamp(profile.base_connections + scale, 50, 2000)


def generate_config(
    memory_gb: float,
    profile: Profile,
    max_connections_override: int | None,
    active_frac: float,
    headroom_frac: float,
    headroom_min_mib: int,
    temp_model_frac: float,
) -> str:
    total_mib = memory_gb * 1024.0

    headroom_mib = max(float(headroom_min_mib), total_mib * headroom_frac)
    budget_mib = max(256.0, total_mib - headroom_mib)

    # Per-connection modeled buffers (conservative).
    thread_stack_mib = 0.25  # ~256 KiB
    net_buffer_mib = 0.25    # rough allowance

    per_conn_mib = (
        profile.sort_buffer_mib
        + profile.join_buffer_mib
        + profile.read_buffer_mib
        + profile.read_rnd_buffer_mib
        + thread_stack_mib
        + net_buffer_mib
    )

    # Pick max_connections.
    if max_connections_override is not None:
        max_connections = int(max_connections_override)
    else:
        max_connections = compute_max_connections(budget_mib, profile)

    active_conns = max(10, int(math.ceil(max_connections * active_frac)))

    # Global-ish allocations / overhead.
    innodb_log_buffer_mib = 64 if budget_mib >= 2048 else 32

    # Cache sizing: moderate defaults (wasteful if set too high).
    table_open_cache = 2000 if budget_mib >= 4096 else 1000
    table_definition_cache = 2000 if budget_mib >= 4096 else 1000
    thread_cache_size = 100 if budget_mib >= 4096 else 50
    performance_schema = "ON" if budget_mib >= 2048 else "OFF"

    # Misc overhead reserve (PFS, dict, internal allocations, etc.)
    misc_mib = 256 if budget_mib >= 2048 else 128

    # Temp table modeling: only some active conns do temp-heavy work.
    temp_mib = active_conns * profile.tmp_table_mib * temp_model_frac

    global_non_pool_mib = innodb_log_buffer_mib + misc_mib
    conn_modeled_mib = active_conns * per_conn_mib + temp_mib

    # Allocate remaining memory to InnoDB buffer pool, but cap at 80% of budget.
    remaining_mib = budget_mib - global_non_pool_mib - conn_modeled_mib
    innodb_buffer_pool_mib = clamp(int(remaining_mib), 256, int(budget_mib * 0.80))

    # Buffer pool instances: 1 per ~1 GiB up to 8.
    innodb_buffer_pool_instances = clamp(int(innodb_buffer_pool_mib / 1024), 1, 8)

    # Redo log size: ~10% of pool, bounded.
    innodb_log_file_size_mib = clamp(int(innodb_buffer_pool_mib * 0.10), 256, 1024)

    # Other safe defaults.
    max_allowed_packet_mib = 64

    innodb_flush_method = "O_DIRECT"
    innodb_flush_log_at_trx_commit = 1  # safest durability
    sync_binlog = 1                     # safest if binlog enabled

    # Per-connection caps for in-memory temp tables.
    tmp_table_size_mib = profile.tmp_table_mib
    max_heap_table_size_mib = profile.tmp_table_mib

    # Query cache should be off in modern setups.
    query_cache_type = 0
    query_cache_size_mib = 0

    # Thread pool helps with many connections.
    thread_handling = "pool-of-threads"

    lines: list[str] = []
    lines.append("# ------------------------------------------------------------")
    lines.append(f"# Generated for MariaDB 12 with memory budget: {memory_gb:.2f} GB")
    lines.append(f"# Budget after headroom: {budget_mib:.0f} MiB (headroom: {headroom_mib:.0f} MiB)")
    lines.append(f"# Profile: {profile.name}")
    lines.append(f"# Modeled active connections: {active_conns} (active_frac={active_frac})")
    lines.append(f"# Modeled per-conn buffers: {per_conn_mib:.2f} MiB")
    lines.append("# ------------------------------------------------------------")
    lines.append("")
    lines.append("[mysqld]")

    def kv(k: str, v: str | int) -> None:
        lines.append(f"{k} = {v}")

    kv("max_connections", max_connections)
    kv("thread_cache_size", thread_cache_size)
    kv("thread_handling", thread_handling)

    kv("table_open_cache", table_open_cache)
    kv("table_definition_cache", table_definition_cache)

    kv("performance_schema", performance_schema)

    kv("innodb_buffer_pool_size", fmt_mib(innodb_buffer_pool_mib))
    kv("innodb_buffer_pool_instances", innodb_buffer_pool_instances)

    kv("innodb_log_buffer_size", fmt_mib(innodb_log_buffer_mib))
    kv("innodb_log_file_size", fmt_mib(innodb_log_file_size_mib))

    kv("innodb_flush_method", innodb_flush_method)
    kv("innodb_flush_log_at_trx_commit", innodb_flush_log_at_trx_commit)
    kv("sync_binlog", sync_binlog)

    kv("max_allowed_packet", fmt_mib(max_allowed_packet_mib))

    kv("tmp_table_size", fmt_mib(tmp_table_size_mib))
    kv("max_heap_table_size", fmt_mib(max_heap_table_size_mib))

    kv("sort_buffer_size", fmt_mib(profile.sort_buffer_mib))
    kv("join_buffer_size", fmt_mib(profile.join_buffer_mib))
    kv("read_buffer_size", fmt_mib(profile.read_buffer_mib))
    kv("read_rnd_buffer_size", fmt_mib(profile.read_rnd_buffer_mib))

    kv("query_cache_type", query_cache_type)
    kv("query_cache_size", fmt_mib(query_cache_size_mib))

    lines.append("")
    lines.append("# Notes:")
    lines.append("# - Conservative starting point intended to respect the memory budget.")
    lines.append("# - If you accept durability tradeoffs: innodb_flush_log_at_trx_commit=2 and sync_binlog=0/100.")
    lines.append("# - If you see many Created_tmp_disk_tables, consider increasing tmp_table_size/max_heap_table_size carefully.")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description="Generate a conservative MariaDB 12 my.cnf snippet from a memory budget.")
    p.add_argument("memory_gb", type=float, help="Memory budget for mysqld in GB (float allowed, e.g. 3.5)")
    p.add_argument("--profile", choices=sorted(PROFILES.keys()), default="general", help="Sizing profile")
    p.add_argument("--max-connections", type=int, default=None, help="Force max_connections (otherwise computed)")
    p.add_argument("--active-frac", type=float, default=0.25, help="Fraction of max_connections assumed active (default 0.25)")
    p.add_argument("--headroom-frac", type=float, default=0.15, help="Headroom fraction reserved (default 0.15)")
    p.add_argument("--headroom-min-mib", type=int, default=256, help="Minimum headroom in MiB (default 256)")
    p.add_argument(
        "--temp-model-frac",
        type=float,
        default=0.30,
        help="Fraction of active connections assumed temp-heavy (default 0.30)",
    )

    args = p.parse_args()
    prof = PROFILES[args.profile]

    if args.memory_gb <= 0:
        raise SystemExit("memory_gb must be > 0")
    if not (0.01 <= args.active_frac <= 1.0):
        raise SystemExit("--active-frac must be between 0.01 and 1.0")
    if not (0.0 <= args.headroom_frac <= 0.9):
        raise SystemExit("--headroom-frac must be between 0 and 0.9")
    if not (0.0 <= args.temp_model_frac <= 1.0):
        raise SystemExit("--temp-model-frac must be between 0 and 1.0")

    print(
        generate_config(
            memory_gb=args.memory_gb,
            profile=prof,
            max_connections_override=args.max_connections,
            active_frac=args.active_frac,
            headroom_frac=args.headroom_frac,
            headroom_min_mib=args.headroom_min_mib,
            temp_model_frac=args.temp_model_frac,
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
