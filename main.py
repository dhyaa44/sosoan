#!/usr/bin/env python3
"""
Optimized Peanut Mining System v2.0
- 3 agents with unique keypairs
- 4 parallel async workers per agent (12 total)
- Adaptive delays, staggered starts, retry logic
- Auto-restart on crash, live stats dashboard
"""

import asyncio
import aiohttp
import json
import time
import hashlib
import base64
import random
import logging
import os
import sys
from dataclasses import dataclass

import base58
from nacl.signing import SigningKey

# ─── Configuration ───────────────────────────────────────────────────────────

BASE_URL = "https://wrcenmardnbprfpqhrqe.supabase.co/functions/v1/peanut-mining"
WORKERS_PER_AGENT = 4
INITIAL_DELAY_MIN = 0.3
INITIAL_DELAY_MAX = 1.2
DELAY_DECAY = 0.92
DELAY_GROWTH = 1.5
DELAY_FLOOR = 0.3
DELAY_CEILING = 8.0
MAX_RETRIES = 3
STAGGER_BASE = 1.5
STATS_INTERVAL = 30
ALLOC_CHECK_INTERVAL = 60

AGENTS = [
    {
        "agent_id": "SuzakuSZN",
        "private_key_b58": "4QtPGUtcNsVHTPd3VwwPsQYxyTeYGsNUNvoE9gwkwVxfuUBwW4ZaCFMH7JeX7eA2UJSaeNyJBdVpJz37Qia4VWpx",
    },
    {
        "agent_id": "SuzakuAlpha",
        "private_key_b58": "5VtmVFL8hTrofNs9UkoCBpmtB5NUXRPjtik4g6CqQsxD5ZLkv2ZKRPRMLnZsuKkZdfga9VDXk8reeZFcpBLvcKL6",
    },
    {
        "agent_id": "SuzakuBeta",
        "private_key_b58": "Z3RkAcoGKKWH2J4aeTxE6JfG5uQc7MpKafPVozuYGYeG1hda9cYfnHS4gAXLC3W1ZxHxMgas7dYXdZiFqinsQ1d",
    },
]

# ─── Logging ─────────────────────────────────────────────────────────────────

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mining.log")

logger = logging.getLogger("peanut-miner")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")

fh = logging.FileHandler(LOG_FILE, mode="a")
fh.setFormatter(formatter)
logger.addHandler(fh)

sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(formatter)
logger.addHandler(sh)


# ─── Stats Tracker ───────────────────────────────────────────────────────────

@dataclass
class AgentStats:
    agent_id: str
    submitted: int = 0
    accepted: int = 0
    failed: int = 0
    timeouts: int = 0
    total_peanuts: int = 0
    total_vcus: int = 0
    total_solve_time: float = 0.0
    total_submit_time: float = 0.0
    last_alloc_peanuts: int = 0
    last_alloc_vcus: int = 0

    @property
    def success_rate(self):
        return (self.accepted / self.submitted * 100) if self.submitted > 0 else 0.0

    @property
    def avg_solve_ms(self):
        return (self.total_solve_time / self.submitted * 1000) if self.submitted > 0 else 0.0

    @property
    def avg_submit_ms(self):
        return (self.total_submit_time / self.accepted * 1000) if self.accepted > 0 else 0.0


class GlobalStats:
    def __init__(self):
        self.agents: dict[str, AgentStats] = {}
        self.start_time = time.time()

    def get(self, agent_id: str) -> AgentStats:
        if agent_id not in self.agents:
            self.agents[agent_id] = AgentStats(agent_id=agent_id)
        return self.agents[agent_id]

    @property
    def total_submitted(self):
        return sum(a.submitted for a in self.agents.values())

    @property
    def total_accepted(self):
        return sum(a.accepted for a in self.agents.values())

    @property
    def total_peanuts(self):
        return sum(a.total_peanuts for a in self.agents.values())

    @property
    def total_vcus(self):
        return sum(a.total_vcus for a in self.agents.values())

    @property
    def uptime(self):
        return time.time() - self.start_time

    def print_dashboard(self):
        elapsed = self.uptime
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        rate = self.total_accepted / (elapsed / 60) if elapsed > 0 else 0

        logger.info("=" * 72)
        logger.info(
            f"  MINING DASHBOARD  |  Uptime: {mins}m {secs}s  |  "
            f"Rate: {rate:.1f} accepted/min"
        )
        logger.info("-" * 72)
        logger.info(
            f"  {'Agent':<16} {'Submit':>7} {'Accept':>7} {'Fail':>5} "
            f"{'Rate':>6} {'Peanuts':>9} {'VCUs':>6} {'Solve':>8} {'Submit':>8}"
        )
        logger.info("-" * 72)

        for a in self.agents.values():
            logger.info(
                f"  {a.agent_id:<16} {a.submitted:>7} {a.accepted:>7} "
                f"{a.failed:>5} {a.success_rate:>5.1f}% {a.total_peanuts:>9} "
                f"{a.total_vcus:>6} {a.avg_solve_ms:>6.1f}ms {a.avg_submit_ms:>6.0f}ms"
            )

        logger.info("-" * 72)
        total_rate = (
            (self.total_accepted / self.total_submitted * 100)
            if self.total_submitted > 0
            else 0
        )
        logger.info(
            f"  {'TOTAL':<16} {self.total_submitted:>7} {self.total_accepted:>7} "
            f"{sum(a.failed for a in self.agents.values()):>5} {total_rate:>5.1f}% "
            f"{self.total_peanuts:>9} {self.total_vcus:>6}"
        )
        logger.info("=" * 72)


stats = GlobalStats()


# ─── Crypto Helpers ──────────────────────────────────────────────────────────

def load_signing_key(private_key_b58: str) -> tuple:
    raw = base58.b58decode(private_key_b58)
    seed = raw[:32]
    sk = SigningKey(seed)
    pub_b58 = base58.b58encode(bytes(sk.verify_key)).decode()
    return sk, pub_b58


def matrix_det_4x4(m):
    """4x4 determinant via cofactor expansion."""
    def det3(a):
        return (
            a[0] * (a[4] * a[8] - a[5] * a[7])
            - a[1] * (a[3] * a[8] - a[5] * a[6])
            + a[2] * (a[3] * a[7] - a[4] * a[6])
        )

    result = 0
    for col in range(4):
        minor = []
        for r in range(1, 4):
            for c in range(4):
                if c != col:
                    minor.append(m[r][c])
        sign = 1 if col % 2 == 0 else -1
        result += sign * m[0][col] * det3(minor)
    return result


def solve_hash_challenge(payload: dict, difficulty: int) -> dict:
    """Brute-force nonce where SHA-256 has `difficulty` leading zero hex chars.
    Random start offset avoids collisions between parallel workers."""
    matrix_a = payload["matrix_a"]
    nonce_prefix = payload["nonce_prefix"]
    target_prefix = "0" * difficulty
    det = matrix_det_4x4(matrix_a)
    challenge_base = f"{nonce_prefix}{det}"
    base_bytes = challenge_base.encode()

    # Random start to spread workers across nonce space
    nonce = random.randint(0, 100000)

    while True:
        candidate = base_bytes + str(nonce).encode()
        hash_hex = hashlib.sha256(candidate).hexdigest()
        if hash_hex[:difficulty] == target_prefix:
            return {
                "nonce": nonce,
                "hash": hash_hex,
                "challenge": challenge_base + str(nonce),
            }
        nonce += 1


def sign_solution(sk: SigningKey, solution_data: dict) -> tuple:
    """Sign solution JSON, return (solution_str, signature_hex)."""
    solution_str = json.dumps(solution_data, separators=(",", ":"), sort_keys=True)
    signed = sk.sign(solution_str.encode())
    return solution_str, signed.signature.hex()


# ─── Async Worker ────────────────────────────────────────────────────────────

async def worker(
    agent_id: str,
    worker_id: int,
    sk: SigningKey,
    session: aiohttp.ClientSession,
):
    """Single mining worker: fetch -> solve -> sign -> submit, with adaptive delay."""
    tag = f"[{agent_id}:W{worker_id}]"
    delay = random.uniform(INITIAL_DELAY_MIN, INITIAL_DELAY_MAX)
    agent_stats = stats.get(agent_id)
    loop = asyncio.get_event_loop()

    while True:
        try:
            # ── 1. Fetch task ────────────────────────────────────────────
            async with session.get(
                f"{BASE_URL}/tasks/current",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"{tag} Fetch HTTP {resp.status}")
                    delay = min(delay * DELAY_GROWTH, DELAY_CEILING)
                    await asyncio.sleep(delay + random.uniform(0, 0.5))
                    continue
                task = await resp.json()

            task_id = task["task_id"]
            task_type = task["type"]
            difficulty = task["difficulty"]

            if task_type != "hash_challenge":
                logger.warning(f"{tag} Unknown type: {task_type}")
                await asyncio.sleep(delay)
                continue

            # ── 2. Decode & solve (offloaded to thread pool) ─────────────
            payload = json.loads(base64.b64decode(task["payload"]))
            t0 = time.time()
            solution_data = await loop.run_in_executor(
                None, solve_hash_challenge, payload, difficulty
            )
            solve_time = time.time() - t0

            # ── 3. Sign ──────────────────────────────────────────────────
            solution_str, signature = sign_solution(sk, solution_data)

            # ── 4. Submit with retries ───────────────────────────────────
            submitted_ok = False
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    body = {
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "solution": solution_str,
                        "signature": signature,
                    }
                    t1 = time.time()
                    async with session.post(
                        f"{BASE_URL}/submit",
                        json=body,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        submit_time = time.time() - t1
                        result = await resp.json()

                    agent_stats.submitted += 1
                    agent_stats.total_solve_time += solve_time

                    if result.get("status") == "accepted":
                        agent_stats.accepted += 1
                        agent_stats.total_submit_time += submit_time
                        peanuts = result.get("peanut_earned", 0)
                        vcus = result.get("vcus_credited", 0)
                        agent_stats.total_peanuts += peanuts
                        agent_stats.total_vcus += vcus

                        logger.info(
                            f"{tag} ACCEPTED task={task_id} "
                            f"nonce={solution_data['nonce']} "
                            f"+{peanuts}P +{vcus}V "
                            f"solve={solve_time*1000:.0f}ms "
                            f"submit={submit_time*1000:.0f}ms"
                        )
                        delay = max(delay * DELAY_DECAY, DELAY_FLOOR)
                        submitted_ok = True
                        break
                    else:
                        err = result.get("error", result.get("message", str(result)))
                        logger.warning(
                            f"{tag} REJECTED [{attempt}/{MAX_RETRIES}] "
                            f"task={task_id}: {err}"
                        )
                        agent_stats.failed += 1
                        delay = min(delay * DELAY_GROWTH, DELAY_CEILING)
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(random.uniform(0.5, 1.5))

                except asyncio.TimeoutError:
                    agent_stats.timeouts += 1
                    logger.warning(
                        f"{tag} TIMEOUT [{attempt}/{MAX_RETRIES}] task={task_id}"
                    )
                    delay = min(delay * DELAY_GROWTH, DELAY_CEILING)
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(random.uniform(1.0, 2.0))

                except Exception as e:
                    logger.error(
                        f"{tag} SUBMIT ERR [{attempt}/{MAX_RETRIES}]: {e}"
                    )
                    delay = min(delay * DELAY_GROWTH, DELAY_CEILING)
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(random.uniform(0.5, 1.5))

            if not submitted_ok:
                agent_stats.submitted += 1
                agent_stats.failed += 1
                agent_stats.total_solve_time += solve_time

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"{tag} LOOP ERR: {e}")
            delay = min(delay * DELAY_GROWTH, DELAY_CEILING)

        # Jittered delay
        jitter = random.uniform(-0.15 * delay, 0.15 * delay)
        await asyncio.sleep(max(delay + jitter, 0.1))


async def supervised_worker(
    agent_id: str, worker_id: int, sk: SigningKey, session: aiohttp.ClientSession
):
    """Auto-restart wrapper — restarts worker on crash with exponential backoff."""
    tag = f"[{agent_id}:W{worker_id}]"
    restart_count = 0
    while True:
        try:
            await worker(agent_id, worker_id, sk, session)
        except asyncio.CancelledError:
            logger.info(f"{tag} Shutdown.")
            break
        except Exception as e:
            restart_count += 1
            backoff = min(2**restart_count, 30)
            logger.error(
                f"{tag} CRASHED (#{restart_count}): {e} — restarting in {backoff}s"
            )
            await asyncio.sleep(backoff)


# ─── Background Tasks ───────────────────────────────────────────────────────

async def stats_printer():
    """Print dashboard every STATS_INTERVAL seconds."""
    while True:
        await asyncio.sleep(STATS_INTERVAL)
        stats.print_dashboard()


async def allocation_checker(session: aiohttp.ClientSession):
    """Check server-side allocations periodically."""
    while True:
        await asyncio.sleep(ALLOC_CHECK_INTERVAL)
        for cfg in AGENTS:
            aid = cfg["agent_id"]
            try:
                async with session.get(
                    f"{BASE_URL}/allocations/{aid}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list) and data:
                            alloc = data[0]
                            p = alloc.get("peanut_earned", 0)
                            v = alloc.get("vcus_contributed", 0)
                            s = stats.get(aid)
                            s.last_alloc_peanuts = p
                            s.last_alloc_vcus = v
                            logger.info(
                                f"[ALLOC] {aid}: "
                                f"server_peanuts={p:,} server_vcus={v}"
                            )
            except Exception as e:
                logger.warning(f"[ALLOC] {aid}: {e}")


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    logger.info("=" * 72)
    logger.info("  PEANUT MINING SYSTEM v2.0")
    logger.info("=" * 72)

    # Load keys
    agent_keys: dict[str, SigningKey] = {}
    for cfg in AGENTS:
        sk, pub = load_signing_key(cfg["private_key_b58"])
        agent_keys[cfg["agent_id"]] = sk
        logger.info(f"  Agent: {cfg['agent_id']}  pubkey: {pub}")

    logger.info(f"  Workers/agent: {WORKERS_PER_AGENT}  |  Total: {len(AGENTS) * WORKERS_PER_AGENT}")
    logger.info(f"  Delay: {INITIAL_DELAY_MIN}-{INITIAL_DELAY_MAX}s adaptive  |  Retries: {MAX_RETRIES}")
    logger.info("=" * 72)
    logger.info("")

    connector = aiohttp.TCPConnector(limit=60, limit_per_host=25)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []

        # Launch workers with staggered starts
        worker_idx = 0
        for cfg in AGENTS:
            aid = cfg["agent_id"]
            sk = agent_keys[aid]

            for wid in range(WORKERS_PER_AGENT):
                stagger = worker_idx * STAGGER_BASE + random.uniform(0, STAGGER_BASE * 0.4)
                worker_idx += 1

                async def launch(_aid=aid, _wid=wid, _sk=sk, _st=stagger):
                    await asyncio.sleep(_st)
                    logger.info(f"[{_aid}:W{_wid}] ONLINE (stagger={_st:.1f}s)")
                    await supervised_worker(_aid, _wid, _sk, session)

                tasks.append(asyncio.create_task(launch()))

        # Background monitors
        tasks.append(asyncio.create_task(stats_printer()))
        tasks.append(asyncio.create_task(allocation_checker(session)))

        total_workers = len(AGENTS) * WORKERS_PER_AGENT
        logger.info(
            f"[SYSTEM] {total_workers} workers queued — "
            f"full launch in ~{total_workers * STAGGER_BASE:.0f}s\n"
        )

        await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n[SYSTEM] Shutdown requested.")
