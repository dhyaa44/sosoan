#!/usr/bin/env python3
"""
Peanut Mining Bot - Continuously fetches tasks, solves hash challenges,
signs solutions with Ed25519, and submits proofs.
"""

import json
import time
import hashlib
import base64
import requests
import base58
from nacl.signing import SigningKey

# ─── Configuration ───────────────────────────────────────────────────────────
BASE_URL = "https://wrcenmardnbprfpqhrqe.supabase.co/functions/v1/peanut-mining"
AGENT_ID = "SuzakuSZN"
PRIVATE_KEY_B58 = "4QtPGUtcNsVHTPd3VwwPsQYxyTeYGsNUNvoE9gwkwVxfuUBwW4ZaCFMH7JeX7eA2UJSaeNyJBdVpJz37Qia4VWpx"
LOOP_DELAY = 2  # seconds between mining cycles

# ─── Derive Ed25519 signing key ─────────────────────────────────────────────
raw_key = base58.b58decode(PRIVATE_KEY_B58)
# Solana-style keypair: first 32 bytes = secret seed, last 32 bytes = public key
seed = raw_key[:32]
signing_key = SigningKey(seed)
verify_key = signing_key.verify_key
print(f"[INIT] Agent: {AGENT_ID}")
print(f"[INIT] Public key: {base58.b58encode(bytes(verify_key)).decode()}")
print(f"[INIT] Mining started...\n")


def fetch_task():
    """Fetch the current task from the server."""
    resp = requests.get(f"{BASE_URL}/tasks/current", timeout=15)
    resp.raise_for_status()
    return resp.json()


def decode_payload(payload_b64):
    """Decode base64 payload to JSON."""
    decoded = base64.b64decode(payload_b64)
    return json.loads(decoded)


def matrix_determinant_4x4(m):
    """Compute determinant of a 4x4 matrix."""
    def det3(a):
        return (a[0]*(a[4]*a[8]-a[5]*a[7])
              - a[1]*(a[3]*a[8]-a[5]*a[6])
              + a[2]*(a[3]*a[7]-a[4]*a[6]))

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


def solve_hash_challenge(task_id, payload, difficulty):
    """
    Find a nonce such that SHA-256(nonce_prefix + nonce) has `difficulty` leading hex zeros.
    """
    matrix_a = payload["matrix_a"]
    nonce_prefix = payload["nonce_prefix"]

    # The target: hash must start with `difficulty` zero hex chars
    target_prefix = "0" * difficulty

    # Compute matrix determinant as part of the challenge data
    det = matrix_determinant_4x4(matrix_a)

    # Build the challenge string: prefix + matrix determinant
    challenge_base = f"{nonce_prefix}{det}"

    print(f"  [SOLVE] Prefix: {nonce_prefix}, Matrix det: {det}, Difficulty: {difficulty}")

    nonce = 0
    start_time = time.time()

    while True:
        # Try: SHA-256(challenge_base + nonce)
        candidate = f"{challenge_base}{nonce}"
        hash_hex = hashlib.sha256(candidate.encode()).hexdigest()

        if hash_hex[:difficulty] == target_prefix:
            elapsed = time.time() - start_time
            print(f"  [FOUND] Nonce: {nonce} | Hash: {hash_hex[:16]}... | Time: {elapsed:.2f}s")
            return {
                "nonce": nonce,
                "hash": hash_hex,
                "challenge": candidate
            }

        nonce += 1

        if nonce % 500000 == 0:
            elapsed = time.time() - start_time
            rate = nonce / elapsed if elapsed > 0 else 0
            print(f"  [MINING] Tried {nonce:,} nonces... ({rate:,.0f} H/s)")


def sign_solution(solution_data):
    """Sign the solution JSON string with Ed25519."""
    solution_str = json.dumps(solution_data, separators=(",", ":"), sort_keys=True)
    signed = signing_key.sign(solution_str.encode())
    signature_hex = signed.signature.hex()
    return solution_str, signature_hex


def submit_solution(task_id, solution_str, signature):
    """Submit the signed solution to the server."""
    body = {
        "agent_id": AGENT_ID,
        "task_id": task_id,
        "solution": solution_str,
        "signature": signature
    }
    resp = requests.post(
        f"{BASE_URL}/submit",
        json=body,
        timeout=60
    )
    return resp.json()


def check_allocations():
    """Check current allocations/earnings."""
    try:
        resp = requests.get(f"{BASE_URL}/allocations/{AGENT_ID}", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def mining_loop():
    """Main mining loop."""
    total_submitted = 0
    total_accepted = 0

    while True:
        try:
            # 1. Fetch current task
            print(f"{'='*60}")
            print(f"[FETCH] Getting current task...")
            task = fetch_task()
            task_id = task["task_id"]
            task_type = task["type"]
            difficulty = task["difficulty"]
            epoch = task["epoch"]

            print(f"  Task: {task_id} | Type: {task_type} | Difficulty: {difficulty} | Epoch: {epoch}")

            if task_type != "hash_challenge":
                print(f"  [SKIP] Unknown task type: {task_type}")
                time.sleep(LOOP_DELAY)
                continue

            # 2. Decode payload
            payload = decode_payload(task["payload"])

            # 3. Solve the hash challenge
            solution_data = solve_hash_challenge(task_id, payload, difficulty)

            # 4. Sign the solution
            solution_str, signature = sign_solution(solution_data)
            print(f"  [SIGN] Solution signed (sig: {signature[:32]}...)")

            # 5. Submit
            print(f"  [SUBMIT] Submitting proof...")
            total_submitted += 1

            try:
                result = submit_solution(task_id, solution_str, signature)
                print(f"  [RESULT] {json.dumps(result, indent=2)}")

                if result.get("status") == "accepted" or result.get("success"):
                    total_accepted += 1
                    vcus = result.get("vcus_credited", result.get("vcus_earned", result.get("vcu_earned", "?")))
                    peanuts = result.get("peanut_earned", result.get("peanuts_earned", "?"))
                    print(f"  [EARNED] VCUs: {vcus} | Peanuts: {peanuts}")
            except requests.exceptions.Timeout:
                print(f"  [TIMEOUT] Submit request timed out, continuing...")
            except Exception as e:
                print(f"  [ERROR] Submit failed: {e}")

            # 6. Check allocations periodically
            if total_submitted % 5 == 0:
                alloc = check_allocations()
                if alloc:
                    print(f"\n  [STATS] Allocations: {json.dumps(alloc, indent=2)}")

            print(f"\n  [TOTAL] Submitted: {total_submitted} | Accepted: {total_accepted}")
            print()

        except requests.exceptions.RequestException as e:
            print(f"[NET ERROR] {e}")
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()

        time.sleep(LOOP_DELAY)


if __name__ == "__main__":
    mining_loop()
